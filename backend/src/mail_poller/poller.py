"""
Poller pipeline: turn one inbound email into a CRM chatter entry (MVP `+crm`).

Order (matches docs/email-poller-architecture.md):
  idempotency -> auto-reply skip -> Step 0 sender auth -> route by +tag ->
  resolve To:/Cc to a contact (create if unknown, +crm only) -> post to chatter.
Anything not filed is dead-lettered with a reason. Never a silent drop.

Collaborators (repo, odoo, authenticate) are injected so the pipeline is unit-
testable with fakes and crafted email.message objects.
"""

import html
import logging
import re
from email.message import Message
from email.utils import getaddresses, parseaddr
from typing import List, Optional

from src.mail_poller.sender_auth import authenticate as _authenticate
from src.mail_poller.sender_auth import auth_results_from_message

logger = logging.getLogger(__name__)

# Stable service identity for this writer. Used as the provenance/trust signal so
# a poller-written record is distinguishable from a human edit. When the poller
# writes to abra, this is the binding's created_by (and needs a scope_access
# grant there). For Odoo chatter today it appears in the message stamp.
SERVICE_URI = "urn:abra:service:email-poller"


def _provenance_body(sender: str, recipient: str, body: str, forwarded: bool = False) -> str:
    """Chatter HTML with a visible provenance line, so the reader sees this was
    added by the poller and from whom (not a human edit)."""
    if forwarded:
        line = (f"via email-poller &middot; forwarded by {html.escape(sender)} "
                f"&middot; original from {html.escape(recipient)}")
    else:
        line = (f"via email-poller &middot; from {html.escape(sender)} "
                f"&middot; to {html.escape(recipient)}")
    return f"<p><em>{line}</em></p><pre>{html.escape(body or '')}</pre>"


_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_FWD_MARKER_RE = re.compile(
    r"(-{2,}\s*Forwarded message|Begin forwarded message|-{2,}\s*Original Message)",
    re.IGNORECASE,
)
_FROM_LINE_RE = re.compile(r"^\s*From:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_INLINE_WROTE_RE = re.compile(r"\bOn\b.+?<?([\w.+-]+@[\w-]+\.[\w.-]+)>?\s*wrote:", re.IGNORECASE | re.DOTALL)


def forwarded_origin_address(body: str) -> Optional[str]:
    """
    The original sender of a forwarded email (the client), pulled from the
    forwarded block. Used when the client is not in To:/Cc (a plain forward).
    """
    if not body:
        return None
    # 1. A forwarded-block header: take the first From: after the marker.
    m = _FWD_MARKER_RE.search(body)
    if m:
        after = body[m.end():]
        fm = _FROM_LINE_RE.search(after)
        if fm:
            em = _EMAIL_RE.search(fm.group(1))
            if em:
                return em.group(0).lower()
    # 2. Inline quote: "On <date>, Name <addr> wrote:"
    im = _INLINE_WROTE_RE.search(body)
    if im:
        return im.group(1).lower()
    return None


def is_auto_reply(msg: Message) -> bool:
    if (msg.get("Auto-Submitted", "no") or "no").lower() != "no":
        return True
    if "bulk" in (msg.get("Precedence", "") or "").lower():
        return True
    _, frm = parseaddr(msg.get("From", "") or "")
    if frm.lower().startswith(("mailer-daemon@", "postmaster@")):
        return True
    return False


def extract_tag(msg: Message, base_local: str) -> str:
    """
    Find the +TAG the mail was sent to. Scans the headers that carry the
    delivery address. Defaults to 'crm' when none is visible (common for BCC,
    where Gmail may not preserve the +tag) since the inbox is the CRM inbox.
    """
    pat = re.compile(rf"\b{re.escape(base_local)}\+([a-z0-9_]+)@", re.IGNORECASE)
    for header in ("Delivered-To", "X-Original-To", "To", "Cc"):
        for value in msg.get_all(header, []):
            m = pat.search(value or "")
            if m:
                return m.group(1).lower()
    return "crm"


def recipient_addresses(msg: Message, exclude_locals: List[str]) -> List[str]:
    """To: + Cc: addresses, lowercased, excluding our own inbox addresses."""
    pairs = getaddresses(msg.get_all("To", []) + msg.get_all("Cc", []))
    out, seen = [], set()
    for _, addr in pairs:
        a = addr.lower().strip()
        if not a or "@" not in a:
            continue
        local = a.split("@", 1)[0].split("+", 1)[0]
        if local in exclude_locals:   # our own inbox (base or +tag forms)
            continue
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


def _name_for(msg: Message, address: str) -> str:
    for name, addr in getaddresses(msg.get_all("To", []) + msg.get_all("Cc", [])):
        if addr.lower() == address and name:
            return name
    return address.split("@", 1)[0]


def body_text(msg: Message) -> str:
    """Prefer text/plain; fall back to stripped HTML."""
    if msg.is_multipart():
        plain = _first_part(msg, "text/plain")
        if plain is not None:
            return plain
        html = _first_part(msg, "text/html")
        return _strip_html(html) if html else ""
    payload = msg.get_payload(decode=True)
    text = payload.decode(msg.get_content_charset() or "utf-8", "replace") if payload else (msg.get_payload() or "")
    return _strip_html(text) if (msg.get_content_type() == "text/html") else text


def _first_part(msg: Message, ctype: str) -> Optional[str]:
    for part in msg.walk():
        if part.get_content_type() == ctype and "attachment" not in (part.get("Content-Disposition", "") or ""):
            payload = part.get_payload(decode=True)
            if payload is not None:
                return payload.decode(part.get_content_charset() or "utf-8", "replace")
    return None


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


class Poller:
    def __init__(self, config, repo, odoo, authenticate=_authenticate):
        self.config = config
        self.repo = repo
        self.odoo = odoo
        self._authenticate = authenticate
        self._base_local = (config.imap_user.split("@", 1)[0] or "").lower()

    def process(self, msg: Message) -> str:
        """Process one message. Returns a short status string."""
        mid = (msg.get("Message-ID") or "").strip()
        subject = msg.get("Subject", "") or ""

        if not mid:
            self.repo.dead_letter("no_message_id", from_addr=parseaddr(msg.get("From", ""))[1],
                                  subject=subject)
            return "no_message_id"

        if self.repo.is_seen(mid):
            return "duplicate"

        if is_auto_reply(msg):
            self.repo.mark_seen(mid)
            return "auto_reply_skipped"

        from_hdr = msg.get("From", "") or ""
        ok, reason = self._authenticate(
            from_hdr, auth_results_from_message(msg),
            self.config.allowlist, self.config.trusted_domains,
            getattr(self.config, "trusted_authserv", ("google.com",)),
        )
        if not ok:
            self.repo.dead_letter(reason, message_id=mid, from_addr=parseaddr(from_hdr)[1],
                                  subject=subject)
            self.repo.mark_seen(mid)
            return reason

        tag = extract_tag(msg, self._base_local)
        if tag != "crm":
            self.repo.dead_letter("unrouted_tag", message_id=mid, from_addr=parseaddr(from_hdr)[1],
                                  subject=subject, tag=tag, detail=f"+{tag} not handled yet")
            self.repo.mark_seen(mid)
            return "unrouted_tag"

        sender = parseaddr(from_hdr)[1]
        body = body_text(msg)
        recips = recipient_addresses(msg, exclude_locals=[self._base_local])
        forwarded = False
        if recips:
            target, skipped = recips[0], recips[1:]
        else:
            # No client in To:/Cc — a plain forward. File under the original sender.
            target, skipped, forwarded = forwarded_origin_address(body), [], True
            if not target:
                self.repo.dead_letter("no_recipient", message_id=mid, from_addr=sender,
                                      subject=subject, tag="crm")
                self.repo.mark_seen(mid)
                return "no_recipient"

        partner_id = self.odoo.find_partner_by_email(target)
        created = False
        if partner_id is None:
            partner_id = self.odoo.create_partner(_name_for(msg, target), target)
            created = True

        self.odoo.post_message(
            partner_id, subject, _provenance_body(sender, target, body, forwarded=forwarded))

        for other in skipped:
            self.repo.dead_letter("skipped_recipient", message_id=mid, to_addrs=other,
                                  subject=subject, tag="crm", detail=f"filed under {target}")

        self.repo.mark_seen(mid)
        return "filed_created" if created else "filed"
