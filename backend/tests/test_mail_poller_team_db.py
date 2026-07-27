"""
Per-team database resolution in the poller's Odoo client: one process, one set
of credentials, a different database per team.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mail_poller.odoo_client import OdooClient, TeamRoutingDisabled


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("ODOO_URL", "https://crm.example.org")
    monkeypatch.setenv("ODOO_DB", "linkedtrust_crm")
    monkeypatch.setenv("ODOO_USER", "someone@example.org")
    monkeypatch.setenv("ODOO_API_KEY", "k")


def test_for_team_names_the_database_from_the_slug(monkeypatch):
    monkeypatch.setenv("ODOO_TEAM_DB_PATTERN", "crm-{slug}")
    c = OdooClient()
    assert c.for_team("vc").db == "crm-vc"
    assert c.db == "linkedtrust_crm"          # the default client is untouched


def test_for_team_shares_credentials_and_url(monkeypatch):
    monkeypatch.setenv("ODOO_TEAM_DB_PATTERN", "crm-{slug}")
    c = OdooClient()
    t = c.for_team("vc")
    assert (t.url, t.user, t.pwd) == (c.url, c.user, c.pwd)


def test_for_team_is_cached(monkeypatch):
    monkeypatch.setenv("ODOO_TEAM_DB_PATTERN", "crm-{slug}")
    c = OdooClient()
    assert c.for_team("vc") is c.for_team("vc")


def test_no_team_returns_the_default_client(monkeypatch):
    monkeypatch.setenv("ODOO_TEAM_DB_PATTERN", "crm-{slug}")
    c = OdooClient()
    assert c.for_team("") is c


def test_without_the_pattern_a_team_is_refused_not_defaulted(monkeypatch):
    monkeypatch.delenv("ODOO_TEAM_DB_PATTERN", raising=False)
    c = OdooClient()
    with pytest.raises(TeamRoutingDisabled):
        c.for_team("vc")
