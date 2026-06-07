"""Tests for the +intake routing → abra bucket (capture). Fakes only."""

import email
from types import SimpleNamespace

from src.mail_poller.poller import Poller

DKIM = "mx.google.com; dkim=pass header.i=@gmail.com; spf=pass; dmarc=pass"


def cfg():
    return SimpleNamespace(
        imap_user="amebo2019@gmail.com",
        allowlist=["btucson1@gmail.com"],
        trusted_domains=["linkedtrust.us"],
    )


class FakeRepo:
    def __init__(self):
        self.seen = set()
        self.dead = []

    def is_seen(self, mid):
        return mid in self.seen

    def mark_seen(self, mid):
        self.seen.add(mid)

    def dead_letter(self, reason, **kw):
        self.dead.append({"reason": reason, **kw})


class FakeOdoo:
    def find_partner_by_email(self, e):
        return 1

    def create_partner(self, n, e):
        return 1

    def post_message(self, *a, **k):
        return 1


def msg(delivered, subject="Hello", body="hi", mid="<abc@x>"):
    raw = (
        f"From: Golda <btucson1@gmail.com>\nTo: amebo <{delivered}>\n"
        f"Subject: {subject}\nMessage-ID: {mid}\n"
        f"Authentication-Results: {DKIM}\nDelivered-To: {delivered}\n\n{body}\n"
    )
    return email.message_from_string(raw)


class CapturingSink:
    def __init__(self):
        self.items = []

    def __call__(self, item):
        self.items.append(item)


def test_intake_tag_deposits_to_bucket():
    sink = CapturingSink()
    repo = FakeRepo()
    p = Poller(cfg(), repo, FakeOdoo(), intake_sink=sink)
    m = msg("amebo2019+intake@gmail.com", subject="Partner deck",
            body="see https://example.com/deck and https://x.io/a please")
    assert p.process(m) == "intake_filed"
    assert len(sink.items) == 1
    it = sink.items[0]
    assert it["name"].startswith("intake-")
    assert it["cat"].startswith("amebo/intake/")
    assert "Partner deck" in it["summary"]
    assert "https://example.com/deck" in it["content"]
    assert "https://x.io/a" in it["content"]
    assert "<abc@x>" in repo.seen


def test_intake_summary_capped_100():
    sink = CapturingSink()
    p = Poller(cfg(), FakeRepo(), FakeOdoo(), intake_sink=sink)
    p.process(msg("amebo2019+intake@gmail.com", subject="x" * 200))
    assert len(sink.items[0]["summary"]) <= 100


def test_intake_sink_failure_dead_letters_not_silent():
    def boom(item):
        raise RuntimeError("abra down")
    repo = FakeRepo()
    p = Poller(cfg(), repo, FakeOdoo(), intake_sink=boom)
    p.process(msg("amebo2019+intake@gmail.com"))
    assert any(d["reason"] == "intake_sink_failed" for d in repo.dead)


def test_crm_path_does_not_trigger_intake():
    sink = CapturingSink()
    p = Poller(cfg(), FakeRepo(), FakeOdoo(), intake_sink=sink)
    # A +crm message goes down the CRM branch, never the intake sink.
    result = p.process(msg("amebo2019+crm@gmail.com"))
    assert result != "intake_filed"
    assert sink.items == []
