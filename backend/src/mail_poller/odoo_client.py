"""
Minimal Odoo XML-RPC client for the poller: resolve / create a contact and post
to its chatter. Structured calls (not parsing odoo-cli text output), but the same
auth pattern (ODOO_API_KEY / ODOO_USER).

This is the Writer + OdooResolver from the design, as a Python client so the
poller has no fragile shell-output parsing. The human-facing `odoo-cli log` verb
is a separate convenience; both end at the same `message_post`.

One process serves every team. A deployment where each team's CRM is its own
database names them from the team slug (ODOO_TEAM_DB_PATTERN, e.g. 'crm-{slug}',
the same variable amebo's CRM tools already use); `for_team(slug)` returns a
client bound to that database. Credentials, URL and everything else are shared,
exactly as they are for the tools.
"""

import logging
import os
import xmlrpc.client
from typing import Optional

logger = logging.getLogger(__name__)


class TeamRoutingDisabled(RuntimeError):
    """A mail addressed to a team arrived, but this deployment has no per-team
    database naming (ODOO_TEAM_DB_PATTERN unset). Refusing rather than filing it
    into whatever ODOO_DB happens to be: that would put one team's mail in
    another team's CRM."""


class OdooClient:
    def __init__(self, db: Optional[str] = None):
        self.url = os.getenv("ODOO_URL", "http://localhost:8069")
        self.db = db or os.getenv("ODOO_DB", "linkedtrust_crm")
        self.user = os.getenv("ODOO_USER", "admin")
        self.pwd = os.getenv("ODOO_API_KEY", "") or os.getenv("ODOO_PASSWORD", "")
        self.team_db_pattern = os.getenv("ODOO_TEAM_DB_PATTERN", "").strip()
        self._uid = None
        self._models = None
        self._team_clients = {}

    def for_team(self, slug: str) -> "OdooClient":
        """A client bound to that team's CRM database. Cached, so a busy inbox
        authenticates once per team rather than once per message."""
        if not slug:
            return self
        if not self.team_db_pattern:
            raise TeamRoutingDisabled(
                f"mail addressed to team '{slug}' but ODOO_TEAM_DB_PATTERN is unset"
            )
        db = self.team_db_pattern.format(slug=slug)
        if db == self.db:
            return self
        if db not in self._team_clients:
            self._team_clients[db] = OdooClient(db=db)
        return self._team_clients[db]

    def _connect(self):
        if self._uid is not None:
            return
        common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
        self._uid = common.authenticate(self.db, self.user, self.pwd, {})
        if not self._uid:
            raise RuntimeError("Odoo authentication failed (check ODOO_USER / ODOO_API_KEY)")
        self._models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")

    def _kw(self, model, method, args, kwargs=None):
        self._connect()
        return self._models.execute_kw(self.db, self._uid, self.pwd, model, method, args, kwargs or {})

    def find_partner_by_email(self, email: str) -> Optional[int]:
        rows = self._kw("res.partner", "search_read",
                        [[("email", "=ilike", email)]], {"fields": ["id"], "limit": 1})
        return rows[0]["id"] if rows else None

    def create_partner(self, name: str, email: str) -> int:
        pid = self._kw("res.partner", "create", [{"name": name or email, "email": email}])
        logger.info("created partner %s <%s> id=%s", name, email, pid)
        return pid

    def post_message(self, partner_id: int, subject: str, body: str,
                     message_type: str = "email") -> int:
        return self._kw("res.partner", "message_post", [partner_id], {
            "body": body,
            "subject": subject,
            "message_type": message_type,
            "subtype_xmlid": "mail.mt_comment",
        })
