"""
Concrete ContactReader over the LinkedTrust Odoo CRM.

The real adapter for the ``ContactReader`` Protocol (defined in ``contact_claw``),
exactly as ``taiga_task_reader`` is the real adapter for ``TaskReader``. Building
it here keeps the claw storage-agnostic: the claw depends only on the Protocol
and the ``Contact`` projection; this module is the single place that knows about
Odoo, XML-RPC, and the CRM's field shapes.

What an "outreach contact" is (Golda's CRM model): a CRM **opportunity**
(``crm.lead`` of type ``opportunity``) joined to the person it is about
(``res.partner``). The lead carries the outreach framing (its tags, its UTM
campaign); the partner carries who they are (name, job function, free-text
comment). The claw scores that joined view against the outreach rubric.

Odoo access reuses the SAME auth path as the mail poller (``OdooClient`` →
XML-RPC to ``localhost:8069``, db ``linkedtrust_crm``, creds from
``ODOO_API_KEY`` / ``ODOO_PASSWORD``). This is a **service / team** credential
(BOUNDARIES.md: background claw work runs under the team's service identity,
never a per-user god-token). The Odoo call surface is INJECTED (``search_read``)
so tests exercise the join/normalization with a fake and never touch a live CRM,
mirroring ``taiga_task_reader``'s injected ``runner``.

Odoo shapes this adapter relies on (stable Odoo 17 conventions):

  - a many2one field (``partner_id``, ``campaign_id``) read via ``search_read``
    comes back as ``[id, "Display Name"]`` or ``False`` when unset;
  - a many2many field (``tag_ids``) comes back as a list of ids; the names are
    resolved with one extra ``search_read`` on ``crm.tag``.

Which CRM / which subset of leads belongs to a given org is, like Taiga's
org→login mapping, an integration decision — Odoo has no "organization" object,
an org IS the CRM this adapter is pointed at. This adapter reads the CRM it is
configured for; per-org scoping (if several orgs ever share one Odoo) is a
wiring concern documented in docs/CONTACT_CLAW.md, not invented here.
"""

from __future__ import annotations

import html
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Sequence

from src.services.contact_claw import Contact

logger = logging.getLogger(__name__)

# search_read(model, domain, fields=None, limit=None, order=None) -> list[dict].
# Structurally identical to OdooClient.search_read; injected so tests supply a
# fake and no XML-RPC happens in the pure path.
SearchRead = Callable[..., List[Dict[str, Any]]]

# The CRM lead fields the claw needs. Kept as a constant so the read stays lean
# (never SELECT *) and the field list is auditable.
_LEAD_FIELDS = ["name", "partner_id", "function", "email_from", "tag_ids", "campaign_id"]
_PARTNER_FIELDS = ["name", "function", "comment", "email"]


def _default_search_read() -> SearchRead:
    """Build the real Odoo access path lazily (so importing this module never
    requires a live CRM). Reuses the mail poller's ``OdooClient`` — one Odoo
    auth path for the whole backend, not a second connection."""
    from src.mail_poller.odoo_client import OdooClient

    client = OdooClient()

    def _run(model, domain, fields=None, limit=None, order=None):
        return client.search_read(model, domain, fields=fields, limit=limit, order=order)

    return _run


def _strip_html(raw: Optional[str]) -> str:
    """Odoo stores ``comment`` as HTML. Reduce it to plain text: drop tags,
    unescape entities, collapse whitespace. Pure and dependency-free."""
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _m2o_name(value: Any) -> Optional[str]:
    """A many2one from search_read is ``[id, "Name"]`` or ``False``."""
    if isinstance(value, (list, tuple)) and len(value) == 2:
        name = str(value[1]).strip()
        return name or None
    return None


def _m2o_id(value: Any) -> Optional[int]:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        try:
            return int(value[0])
        except (TypeError, ValueError):
            return None
    return None


class OdooContactReader:
    """Reads outreach contacts (crm.lead ⋈ res.partner) from the CRM as
    ``Contact`` projections."""

    def __init__(
        self,
        search_read: Optional[SearchRead] = None,
        *,
        lead_domain: Optional[list] = None,
        max_leads: int = 500,
    ):
        # Default to real opportunities; injectable for tests / other scopes.
        self._search_read = search_read or _default_search_read()
        # Only opportunities (not raw leads) are outreach targets worth ranking.
        self._lead_domain = lead_domain if lead_domain is not None else [("type", "=", "opportunity")]
        self._max_leads = max_leads

    def list_contacts(self, *, org_id: int) -> Sequence[Contact]:
        leads = self._safe_read("crm.lead", self._lead_domain, _LEAD_FIELDS,
                                limit=self._max_leads)
        if not leads:
            logger.info("[contact-reader] org=%s: no opportunities in CRM", org_id)
            return []

        partners = self._load_partners(leads)
        tags = self._load_tag_names(leads)

        out: List[Contact] = []
        for lead in leads:
            lead_id = lead.get("id")
            if lead_id is None:
                continue
            partner_id = _m2o_id(lead.get("partner_id"))
            partner = partners.get(partner_id, {}) if partner_id is not None else {}

            # Name: prefer the linked partner; fall back to the lead's own label.
            name = (partner.get("name") or _m2o_name(lead.get("partner_id"))
                    or lead.get("name") or "").strip()
            # Role/function: partner's job position, else the lead's contact function.
            role = (partner.get("function") or lead.get("function") or "").strip() or None
            # Note: the partner's free-text comment, HTML-stripped.
            note = _strip_html(partner.get("comment"))
            # Reachability signal (never a hard filter here — the rubric decides).
            has_email = bool(
                (partner.get("email") or "").strip()
                or (lead.get("email_from") or "").strip()
            )
            contact_tags = tuple(
                tags.get(tid, "") for tid in (lead.get("tag_ids") or [])
                if tags.get(tid)
            )

            out.append(Contact(
                key=f"lead-{lead_id}",
                name=name,
                role=role,
                tags=contact_tags,
                campaign=_m2o_name(lead.get("campaign_id")),
                note=note,
                has_email=has_email,
            ))
        return out

    # -- helpers -------------------------------------------------------------

    def _load_partners(self, leads: Sequence[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
        ids = sorted({pid for pid in (_m2o_id(l.get("partner_id")) for l in leads)
                      if pid is not None})
        if not ids:
            return {}
        rows = self._safe_read("res.partner", [("id", "in", ids)], _PARTNER_FIELDS)
        return {r["id"]: r for r in rows if "id" in r}

    def _load_tag_names(self, leads: Sequence[Dict[str, Any]]) -> Dict[int, str]:
        ids = sorted({tid for l in leads for tid in (l.get("tag_ids") or [])})
        if not ids:
            return {}
        rows = self._safe_read("crm.tag", [("id", "in", ids)], ["name"])
        return {r["id"]: str(r.get("name", "")).strip()
                for r in rows if "id" in r}

    def _safe_read(self, model, domain, fields, limit=None) -> List[Dict[str, Any]]:
        """One search_read that never raises: a CRM outage degrades a claw tick
        to 'no contacts', never a crash (same discipline as the Taiga reader)."""
        try:
            rows = self._search_read(model, domain, fields=fields, limit=limit)
        except Exception as e:  # noqa: BLE001 — deliberate: degrade, don't crash
            logger.warning("[contact-reader] %s read failed: %s", model, e)
            return []
        return list(rows) if isinstance(rows, (list, tuple)) else []
