"""
Minimal Odoo XML-RPC client for the poller: resolve / create a contact and post
to its chatter. Structured calls (not parsing odoo-cli text output), but the same
auth pattern (ODOO_API_KEY / ODOO_USER).

This is the Writer + OdooResolver from the design, as a Python client so the
poller has no fragile shell-output parsing. The human-facing `odoo-cli log` verb
is a separate convenience; both end at the same `message_post`.
"""

import logging
import os
import xmlrpc.client
from typing import Optional

logger = logging.getLogger(__name__)


class OdooClient:
    def __init__(self):
        self.url = os.getenv("ODOO_URL", "http://localhost:8069")
        self.db = os.getenv("ODOO_DB", "linkedtrust_crm")
        self.user = os.getenv("ODOO_USER", "admin")
        self.pwd = os.getenv("ODOO_API_KEY", "") or os.getenv("ODOO_PASSWORD", "")
        self._uid = None
        self._models = None

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
