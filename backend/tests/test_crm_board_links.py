"""Tests for the config-selected CRM link enrichers (vendor leaf).

The Odoo read is monkeypatched — no network. Covers ref matching, the no-op
paths (unknown/absent key), and fail-soft on Odoo errors.
"""

import pytest

from src.services import crm_board_links as cbl


@pytest.fixture(autouse=True)
def _clear_cache():
    cbl._cache["at"] = 0.0
    cbl._cache["by_ref"] = {}
    yield


def test_attach_matches_ref_path(monkeypatch):
    monkeypatch.setattr(
        cbl, "_campaign_form_urls_by_ref",
        lambda: {"campaigns/ae-feedback/MAIN.md": "https://crm.example/web#id=7&model=utm.campaign&view_type=form"},
    )
    items = [
        {"ref_path": "campaigns/ae-feedback/MAIN.md", "crm_url": None},
        {"ref_path": "campaigns/other/MAIN.md", "crm_url": None},
    ]
    cbl.attach_odoo_utm_campaign(items)
    assert items[0]["crm_url"].endswith("id=7&model=utm.campaign&view_type=form")
    assert items[1]["crm_url"] is None  # no matching campaign -> left alone


def test_enrich_crm_links_dispatch(monkeypatch):
    monkeypatch.setattr(
        cbl, "_campaign_form_urls_by_ref",
        lambda: {"campaigns/ae-feedback/MAIN.md": "https://crm.example/web#id=7&model=utm.campaign&view_type=form"},
    )
    items = [{"ref_path": "campaigns/ae-feedback/MAIN.md", "crm_url": None}]
    cbl.enrich_crm_links(items, "odoo_utm_campaign")
    assert items[0]["crm_url"] is not None


def test_enrich_no_key_is_noop():
    items = [{"ref_path": "campaigns/ae-feedback/MAIN.md", "crm_url": None}]
    cbl.enrich_crm_links(items, None)
    cbl.enrich_crm_links(items, "unknown_kind")
    assert items[0]["crm_url"] is None


def test_resolve_fail_soft_on_odoo_error(monkeypatch):
    def boom():
        raise RuntimeError("odoo down")
    monkeypatch.setattr("src.tools.cli_read_tools._odoo", boom, raising=False)
    # _campaign_form_urls_by_ref swallows and returns {}
    assert cbl._campaign_form_urls_by_ref() == {}
    items = [{"ref_path": "campaigns/ae-feedback/MAIN.md", "crm_url": None}]
    cbl.attach_odoo_utm_campaign(items)  # must not raise
    assert items[0]["crm_url"] is None
