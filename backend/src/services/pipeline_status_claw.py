"""Pipeline-status claw.

The two things that quietly kill a sales pipeline are deals with **no scheduled
next step** and deals that have **gone stale**. This claw sweeps the CRM
pipeline, finds those, and drafts ONE gated digest to a configured channel so a
human can act. It never reassigns, never closes, never posts on its own.

Why Odoo (not Taiga) is the source here: the lightweight "next step" we already
put on a deal is an Odoo **Activity** (``activity_date_deadline``, set via
``odoo-cli schedule`` / the sales-coach skill). So a single ``crm.lead`` read
answers both questions — staleness from ``write_date``, missing-next-step from an
empty ``activity_date_deadline``. (Heavier, cash-tagged to-dos still live in
Taiga; this claw is about pipeline *hygiene*, which is the Activity signal.)

Discipline (identical to followup_claw / opportunity_claw):
- Outbound is a single gated draft (slack_post via the draft-approval gate) —
  nothing posts without a human approving. One digest, never one-per-deal.
- Dedup is by the amebo pending_actions table (payload.pipeline_digest + same
  day), so re-running the sweep posts at most one digest per channel per day.
- The notify channel is injected config, never hardcoded; no channel → no-op.
- The CRM read is injected so tests pass a fake instead of hitting Odoo.

Scope note: our Odoo is single-tenant (it IS WhatsCookin's CRM), so the read is
not org-filtered — matching ``crm_list_leads``. ``org_id`` still scopes the gate
and the dedup. A multi-tenant CRM would add an org filter to the reader.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# A deal with no Activity in this many days (by last write) is "stale".
DEFAULT_STALE_DAYS = 14
# Keep the digest scannable: show a small sample, link to the rest in the CRM.
SAMPLE_SIZE = 5
# Public CRM base for clickable deep-links (env-overridable, never hardcoded in
# logic). XML-RPC talks to localhost; humans click the public URL.
ODOO_PUBLIC_URL = os.getenv("ODOO_PUBLIC_URL", "https://crm.linkedtrust.us").rstrip("/")


def _lead_url(lead_id: Any) -> str:
    """Deep-link to a lead in the Odoo 17 web client (classic /web router —
    the /odoo/* paths 404 on this build). The #fragment is client-side, so a
    logged-in teammate lands directly on the record."""
    return f"{ODOO_PUBLIC_URL}/web#id={lead_id}&model=crm.lead&view_type=form"


def _pipeline_url() -> str:
    return f"{ODOO_PUBLIC_URL}/web#model=crm.lead&view_type=list"


def _slack_link(url: str, label: str) -> str:
    """A Slack ``<url|label>`` link with both parts escaped. Slack treats
    ``&``/``<``/``>`` as control characters, so an unescaped ``&`` in a URL
    (ours has ``&model=…&view_type=…``) truncates the link target. Escaping is
    required for the deep-link to actually open the specific record."""
    def esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"<{esc(url)}|{esc(label)}>"


# ---------------------------------------------------------------------------
# Pure core — fully injectable, no I/O of its own
# ---------------------------------------------------------------------------


def classify(leads: List[Dict], *, today: str, stale_days: int) -> Dict[str, List[Dict]]:
    """Split open deals into the two hygiene buckets.

    ``no_next_step``: no scheduled Activity (empty ``activity_date_deadline``).
    ``stale``: not updated in ``stale_days`` (by ``write_date``). A deal can be
    in both; ``no_next_step`` takes precedence so it isn't double-listed.
    """
    cutoff = (datetime.fromisoformat(today).date() - timedelta(days=stale_days)).isoformat()
    no_next_step: List[Dict] = []
    stale: List[Dict] = []
    for l in leads:
        if not (l.get("activity_date_deadline")):
            no_next_step.append(l)
            continue
        if (l.get("write_date") or "")[:10] < cutoff:
            stale.append(l)
    return {"no_next_step": no_next_step, "stale": stale}


def _line(l: Dict) -> str:
    """One concise, clickable line: linked deal name · stage."""
    stage = l["stage_id"][1] if l.get("stage_id") else "-"
    name = l.get("name") or l.get("partner_name") or "(no name)"
    lead_id = l.get("id")
    if lead_id:
        return f"• {_slack_link(_lead_url(lead_id), name)} · {stage}"
    return f"• {name} · {stage}"


def build_digest(buckets: Dict[str, List[Dict]], *, today: str, stale_days: int) -> Optional[str]:
    """One short, crystallized pipeline-hygiene message, or None if clean.

    Leads with the counts, then a small clickable sample of the priority bucket
    (no-next-step first), then a link to the rest in the CRM. Deliberately brief
    so a weekly ping informs without nagging."""
    no_step = buckets["no_next_step"]
    stale = buckets["stale"]
    if not no_step and not stale:
        return None

    counts = []
    if no_step:
        counts.append(f"*{len(no_step)}* with no next step")
    if stale:
        counts.append(f"*{len(stale)}* gone quiet (>{stale_days}d)")
    parts = [f"🩺 *Pipeline check · {today}* — " + ", ".join(counts) + "."]

    primary = no_step or stale
    label = "No next step" if no_step else f"Gone quiet (>{stale_days}d)"
    sample = primary[:SAMPLE_SIZE]
    parts.append(f"\n_{label}, e.g.:_")
    parts += [_line(l) for l in sample]
    remaining = len(primary) - len(sample)
    if remaining > 0:
        parts.append(_slack_link(_pipeline_url(), f"…and {remaining} more in the CRM"))

    parts.append("\nGive one a next step — reply `@amebo coach me on <name>`.")
    return "\n".join(parts)


def run_pipeline_status(
    org_id: int,
    channel: str,
    *,
    reader: Optional[Callable[[], List[Dict]]] = None,
    gate: Optional[Callable[[str, str, str], Any]] = None,
    already_drafted: Optional[Callable[[str], bool]] = None,
    today: Optional[str] = None,
    stale_days: int = DEFAULT_STALE_DAYS,
) -> Dict[str, Any]:
    """Sweep the pipeline and draft one gated digest. Returns a summary dict.

    Injectable: ``reader`` (``() -> [lead dict]``; defaults to the real Odoo
    read), ``gate`` (``(channel, text, key) -> result``; defaults to the gated
    slack draft), ``already_drafted`` (``key -> bool`` dedup; defaults to the
    pending_actions check), ``today`` (defaults to the real date).
    """
    if not channel:
        logger.warning("pipeline_status_claw: no notify channel configured; skipping.")
        return {"drafted": 0, "reason": "no_channel"}

    today = today or date.today().isoformat()
    reader = reader or (lambda: _read_open_leads())
    if already_drafted is None:
        already_drafted = lambda key: _already_drafted_db(org_id, key, today)
    if gate is None:
        gate = lambda channel, text, key: _draft_slack(org_id, channel, text, key)

    key = f"{channel}:{today}"
    if already_drafted(key):
        logger.info("pipeline_status_claw: digest already drafted today for %s", channel)
        return {"drafted": 0, "reason": "already_drafted", "channel": channel, "date": today}

    try:
        leads = reader()
    except Exception as e:
        logger.warning("pipeline_status_claw: could not read pipeline: %s", e)
        return {"drafted": 0, "reason": "read_failed", "error": str(e)}

    buckets = classify(leads, today=today, stale_days=stale_days)
    digest = build_digest(buckets, today=today, stale_days=stale_days)
    if digest is None:
        logger.info("pipeline_status_claw: pipeline clean, nothing to flag.")
        return {"drafted": 0, "reason": "clean", "channel": channel, "date": today,
                "scanned": len(leads)}

    gate(channel, digest, key)
    summary = {"drafted": 1, "channel": channel, "date": today, "scanned": len(leads),
               "no_next_step": len(buckets["no_next_step"]), "stale": len(buckets["stale"])}
    logger.info("pipeline_status_claw: %s", summary)
    return summary


# ---------------------------------------------------------------------------
# Real implementations of the injectable bits
# ---------------------------------------------------------------------------


def _read_open_leads() -> List[Dict]:
    """Read open (active, not-won) ``crm.lead`` rows with the fields the claw
    needs. Read-only XML-RPC, reusing the same in-process Odoo auth as the read
    tools. Lost leads are already ``active=False`` in Odoo; won deals are
    excluded via ``stage_id.is_won``."""
    from src.tools.cli_read_tools import _odoo
    m, db, uid, pwd = _odoo()
    return m.execute_kw(
        db, uid, pwd, "crm.lead", "search_read",
        [[("active", "=", True), ("stage_id.is_won", "=", False)]],
        {"fields": ["name", "partner_name", "stage_id", "user_id",
                    "expected_revenue", "activity_date_deadline", "write_date"],
         "order": "write_date desc", "limit": 500},
    )


def _draft_slack(org_id: int, channel: str, text: str, key: str) -> str:
    """Route the digest through the draft-approval gate (gated → pending).

    Carries ``pipeline_digest`` in the payload for same-day dedup; the post
    itself reuses the registered execute_slack_post executor, so approval sends
    it like any other slack draft."""
    from src.services.draft_approval_service import DraftApprovalService
    from src.tools.gated_actuators import execute_slack_post
    gate = DraftApprovalService()
    result = gate.gate_or_execute(
        org_id=org_id,
        action_type="slack_post",
        acting_identity=f"amebo:{org_id}",
        executor=execute_slack_post,
        target=channel,
        payload={"channel": channel, "text": text, "pipeline_digest": key,
                 "require_mention": False},  # channel digest, not a personal ping
        preview=f"Pipeline check to {channel}: {text[:120]}",
    )
    return "drafted" if result.gated else (result.result or "executed")


def _already_drafted_db(org_id: int, key: str, today: str) -> bool:
    """True if a pipeline digest for this channel was already drafted today
    (any status) — so we post at most one digest per channel per day."""
    from src.db.connection import DatabaseConnection
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM pending_actions
                WHERE org_id = %s
                  AND action_type = 'slack_post'
                  AND payload->>'pipeline_digest' = %s
                  AND requested_at::date = %s::date
                LIMIT 1
                """,
                (org_id, key, today),
            )
            return cur.fetchone() is not None
    finally:
        DatabaseConnection.return_connection(conn)


def main() -> None:
    """Entry point for a daily timer. Runs the sweep for every instance that has
    a ``notify_channel`` configured (config-driven: no channel → nothing). All
    drafts are gated, so this is safe to run unattended — it never posts on its
    own."""
    from src.db.connection import DatabaseConnection
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT org_id, slug, config->>'notify_channel'
                   FROM instances
                   WHERE org_id IS NOT NULL
                     AND config->>'notify_channel' IS NOT NULL
                     AND config->>'notify_channel' <> ''"""
            )
            rows = cur.fetchall()
    finally:
        DatabaseConnection.return_connection(conn)

    if not rows:
        logger.info("pipeline_status_claw: no instance has notify_channel set; nothing to do.")
        return
    for org_id, slug, channel in rows:
        try:
            summary = run_pipeline_status(org_id, channel)
            logger.info("pipeline_status_claw[%s]: %s", slug, summary)
        except Exception:
            logger.exception("pipeline_status_claw failed for org %s (%s)", org_id, slug)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
