"""
Unit tests for the poller pipeline. No IMAP, no DB, no Odoo: fakes + crafted
email.message objects.
"""

import email
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mail_poller.poller import Poller

DKIM = "mx.google.com; dkim=pass header.i=@gmail.com; spf=pass; dmarc=pass"


def cfg():
    return SimpleNamespace(
        imap_user="amebo2019@gmail.com",
        allowlist=["btucson1@gmail.com"],
        trusted_domains=["linkedtrust.us"],
    )


class FakeRepo:
    def __init__(self, seen=None):
        self.seen = set(seen or [])
        self.dead = []

    def is_seen(self, mid):
        return mid in self.seen

    def mark_seen(self, mid):
        self.seen.add(mid)

    def dead_letter(self, reason, **kw):
        self.dead.append({"reason": reason, **kw})


class FakeOdoo:
    def __init__(self, partners=None):
        self.partners = dict(partners or {})  # email -> id
        self.posts = []
        self.created = []
        self._next = 1000

    def find_partner_by_email(self, email_):
        return self.partners.get(email_.lower())

    def create_partner(self, name, email_):
        self._next += 1
        self.partners[email_.lower()] = self._next
        self.created.append({"name": name, "email": email_, "id": self._next})
        return self._next

    def post_message(self, partner_id, subject, body, message_type="email"):
        self.posts.append({"partner_id": partner_id, "subject": subject, "body": body})
        return len(self.posts)


def make(raw):
    return email.message_from_string(raw)


def msg(from_="Golda <btucson1@gmail.com>", to="Client <client@acme.com>",
        subject="Hello", mid="<abc@x>", dkim=DKIM, delivered="amebo2019+crm@gmail.com",
        body="hi there", extra=""):
    headers = f"From: {from_}\nTo: {to}\nSubject: {subject}\n"
    if mid:
        headers += f"Message-ID: {mid}\n"
    if dkim is not None:
        headers += f"Authentication-Results: {dkim}\n"
    if delivered:
        headers += f"Delivered-To: {delivered}\n"
    headers += extra
    return make(f"{headers}\n{body}\n")


def poller(repo=None, odoo=None):
    return Poller(cfg(), repo or FakeRepo(), odoo or FakeOdoo())


def test_files_onto_existing_contact():
    odoo = FakeOdoo(partners={"client@acme.com": 88})
    repo = FakeRepo()
    p = poller(repo, odoo)
    assert p.process(msg()) == "filed"
    assert odoo.posts[0]["partner_id"] == 88
    assert odoo.posts[0]["subject"] == "Hello"
    assert "hi there" in odoo.posts[0]["body"]
    # provenance / trust signal is visible in the chatter post
    assert "via email-poller" in odoo.posts[0]["body"]
    assert "btucson1@gmail.com" in odoo.posts[0]["body"]
    assert "<abc@x>" in repo.seen


def test_creates_contact_when_unknown_to():
    odoo = FakeOdoo()
    p = poller(odoo=odoo)
    assert p.process(msg()) == "filed_created"
    assert odoo.created[0]["email"] == "client@acme.com"
    assert odoo.posts[0]["partner_id"] == odoo.created[0]["id"]


def test_duplicate_skipped():
    repo = FakeRepo(seen={"<abc@x>"})
    odoo = FakeOdoo()
    assert poller(repo, odoo).process(msg()) == "duplicate"
    assert odoo.posts == []


def test_auto_reply_skipped():
    odoo = FakeOdoo()
    m = msg(extra="Auto-Submitted: auto-replied\n")
    assert poller(odoo=odoo).process(m) == "auto_reply_skipped"
    assert odoo.posts == []


def test_sender_not_allowlisted_dead_letters():
    repo = FakeRepo()
    odoo = FakeOdoo()
    m = msg(from_="Stranger <attacker@gmail.com>")
    assert poller(repo, odoo).process(m) == "sender_not_allowlisted"
    assert odoo.posts == []
    assert repo.dead[0]["reason"] == "sender_not_allowlisted"


def test_dkim_fail_dead_letters():
    repo = FakeRepo()
    m = msg(dkim="mx.google.com; dkim=fail")
    assert poller(repo).process(m) == "dkim_not_passed"
    assert repo.dead[0]["reason"] == "dkim_not_passed"


def test_unrouted_tag_dead_letters():
    repo = FakeRepo()
    odoo = FakeOdoo()
    m = msg(delivered="amebo2019+project@gmail.com")
    assert poller(repo, odoo).process(m) == "unrouted_tag"
    assert odoo.posts == []
    assert repo.dead[0]["tag"] == "project"


def test_default_tag_crm_when_no_plus_address():
    # BCC where Gmail didn't preserve the +tag: defaults to crm.
    odoo = FakeOdoo(partners={"client@acme.com": 5})
    m = msg(delivered="amebo2019@gmail.com")
    assert poller(odoo=odoo).process(m) == "filed"


def test_no_recipient_dead_letters():
    repo = FakeRepo()
    # Only our own inbox in To, no external recipient.
    m = msg(to="amebo2019+crm@gmail.com")
    assert poller(repo).process(m) == "no_recipient"
    assert repo.dead[0]["reason"] == "no_recipient"


def test_multi_recipient_files_first_and_deadletters_rest():
    odoo = FakeOdoo(partners={"a@acme.com": 1, "b@beta.com": 2})
    repo = FakeRepo()
    m = msg(to="A <a@acme.com>, B <b@beta.com>")
    assert poller(repo, odoo).process(m) == "filed"
    assert odoo.posts[0]["partner_id"] == 1
    assert any(d["reason"] == "skipped_recipient" for d in repo.dead)


FWD_BODY = (
    "FYI below.\n\n"
    "---------- Forwarded message ---------\n"
    "From: Pat Client <pat@client.com>\n"
    "Date: Mon, 2 Jun 2026\n"
    "Subject: Proposal\n"
    "To: Golda <gvelez17@gmail.com>\n\n"
    "Here is the signed proposal.\n"
)


def test_forwarded_email_files_under_original_sender():
    # To: is only the poller inbox (no client) -> parse forwarded From.
    odoo = FakeOdoo()
    m = msg(to="amebo2019+crm@gmail.com", subject="Fwd: Proposal", body=FWD_BODY)
    assert poller(odoo=odoo).process(m) == "filed_created"
    assert odoo.created[0]["email"] == "pat@client.com"
    assert "forwarded by btucson1@gmail.com" in odoo.posts[0]["body"]
    assert "original from pat@client.com" in odoo.posts[0]["body"]


def test_forwarded_email_matches_existing_contact():
    odoo = FakeOdoo(partners={"pat@client.com": 77})
    m = msg(to="amebo2019+crm@gmail.com", body=FWD_BODY)
    assert poller(odoo=odoo).process(m) == "filed"
    assert odoo.posts[0]["partner_id"] == 77


def test_inline_forward_on_wrote_form():
    odoo = FakeOdoo()
    body = "thoughts?\n\nOn Mon, Jun 2, 2026, Pat <pat@client.com> wrote:\n> hello\n"
    m = msg(to="amebo2019+crm@gmail.com", body=body)
    assert poller(odoo=odoo).process(m) == "filed_created"
    assert odoo.created[0]["email"] == "pat@client.com"


def test_forward_with_no_parseable_origin_dead_letters():
    repo = FakeRepo()
    m = msg(to="amebo2019+crm@gmail.com", body="just a note, nothing forwarded")
    assert poller(repo).process(m) == "no_recipient"


def test_direct_recipient_takes_priority_over_forwarded_block():
    # If a real client is in To:, use that even if the body also has a forward.
    odoo = FakeOdoo(partners={"client@acme.com": 9})
    m = msg(to="Client <client@acme.com>", body=FWD_BODY)
    assert poller(odoo=odoo).process(m) == "filed"
    assert odoo.posts[0]["partner_id"] == 9   # acme, not pat@client.com


def test_no_message_id_dead_letters():
    repo = FakeRepo()
    m = msg(mid=None)
    assert poller(repo).process(m) == "no_message_id"
    assert repo.dead[0]["reason"] == "no_message_id"
