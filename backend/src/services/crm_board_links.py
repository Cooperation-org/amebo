"""
Optional, config-selected CRM link enrichers for the dashboard board.

This is a vendor LEAF (I11): concrete vendor names live here, never in the
generic board core (``board_service``). The board endpoint looks up an enricher
by the ``crm`` key in the instance's ``config.board`` and, if present, lets it
attach a per-item ``crm_url``. Absent/unknown key -> no enrichment, board still
renders (fail-open on the link, never on the board).

The Odoo enricher resolves each campaign's record id via its ``x_project_ref``
(which points back at the doc's repo-relative path) and builds the direct record
form URL — the reliable per-record Odoo web route, independent of whether the UI
exposes a campaigns menu. One cached read per TTL; fail-soft to no link.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

ODOO_PUBLIC_URL = os.getenv("ODOO_PUBLIC_URL", "https://crm.linkedtrust.us").rstrip("/")
_TTL_S = 60
_cache: Dict[str, Any] = {"at": 0.0, "by_ref": {}}  # {at: monotonic, by_ref: {ref: url}}


def _campaign_form_urls_by_ref() -> Dict[str, str]:
    """{x_project_ref -> Odoo record form URL} for all utm.campaigns that carry a
    project ref. Cached for _TTL_S; fail-soft to the last good map (or {})."""
    now = time.monotonic()
    if (now - _cache["at"]) < _TTL_S and _cache["by_ref"]:
        return _cache["by_ref"]
    try:
        from src.tools.cli_read_tools import _odoo
        m, db, uid, pwd = _odoo()
        rows = m.execute_kw(
            db, uid, pwd, "utm.campaign", "search_read",
            [[("x_project_ref", "!=", False)]],
            {"fields": ["id", "x_project_ref"], "limit": 500},
        )
        by_ref = {
            str(r["x_project_ref"]).strip(): f"{ODOO_PUBLIC_URL}/web#id={r['id']}&model=utm.campaign&view_type=form"
            for r in rows if r.get("x_project_ref")
        }
        _cache["at"] = now
        _cache["by_ref"] = by_ref
        return by_ref
    except Exception as exc:
        logger.info("crm_board_links: Odoo campaign resolve skipped (%s)", exc)
        return _cache.get("by_ref") or {}


def _norm(ref: str) -> str:
    return (ref or "").strip().lstrip("./")


def attach_odoo_utm_campaign(items: List[Dict[str, Any]]) -> None:
    """Attach ``crm_url`` (the campaign's Odoo record form) to each item whose
    ``ref_path`` matches a campaign's ``x_project_ref``. Mutates in place."""
    by_ref = _campaign_form_urls_by_ref()
    if not by_ref:
        return
    norm_map = {_norm(k): v for k, v in by_ref.items()}
    for it in items:
        url = norm_map.get(_norm(it.get("ref_path", "")))
        if url:
            it["crm_url"] = url


# config.board.crm -> enricher. Vendor names live here (leaf), not in the core.
CRM_ENRICHERS: Dict[str, Callable[[List[Dict[str, Any]]], None]] = {
    "odoo_utm_campaign": attach_odoo_utm_campaign,
}


def enrich_crm_links(items: List[Dict[str, Any]], crm_key: Optional[str]) -> None:
    if not crm_key:
        return
    enricher = CRM_ENRICHERS.get(crm_key)
    if enricher:
        try:
            enricher(items)
        except Exception:
            logger.exception("crm_board_links: enricher %r failed", crm_key)
