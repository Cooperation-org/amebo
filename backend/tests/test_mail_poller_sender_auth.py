"""
Unit tests for Step 0 sender authentication (the security gate).
Pure logic, no IMAP, no DB.
"""

import sys
from email.message import Message
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mail_poller.sender_auth import authenticate, auth_results_from_message

ALLOW = ["btucson1@gmail.com", "teammate@gmail.com"]
TRUSTED = ["linkedtrust.us"]

GMAIL_DKIM_PASS = "mx.google.com; dkim=pass header.i=@gmail.com; spf=pass; dmarc=pass"
GMAIL_DKIM_FAIL = "mx.google.com; dkim=fail; spf=softfail; dmarc=fail"


def test_allowlisted_address_with_dkim_pass_accepted():
    ok, reason = authenticate("Golda <btucson1@gmail.com>", [GMAIL_DKIM_PASS], ALLOW, TRUSTED)
    assert ok and reason == "ok"


def test_trusted_domain_with_dkim_pass_accepted():
    ok, reason = authenticate("Someone <someone@linkedtrust.us>", [GMAIL_DKIM_PASS], ALLOW, TRUSTED)
    assert ok and reason == "ok"


def test_allowlisted_but_no_dkim_rejected():
    # Spoofed From of an allowlisted address, but DKIM did not pass.
    ok, reason = authenticate("btucson1@gmail.com", [GMAIL_DKIM_FAIL], ALLOW, TRUSTED)
    assert not ok and reason == "dkim_not_passed"


def test_unknown_sender_rejected_even_with_dkim():
    # Any gmail can DKIM-pass for gmail.com; gmail.com is NOT a trusted domain.
    ok, reason = authenticate("attacker@gmail.com", [GMAIL_DKIM_PASS], ALLOW, TRUSTED)
    assert not ok and reason == "sender_not_allowlisted"


def test_no_dkim_header_rejected():
    ok, reason = authenticate("btucson1@gmail.com", [], ALLOW, TRUSTED)
    assert not ok and reason == "dkim_not_passed"


def test_empty_from_rejected():
    ok, reason = authenticate("", [GMAIL_DKIM_PASS], ALLOW, TRUSTED)
    assert not ok and reason == "no_from_address"


def test_free_provider_domain_never_trusted_by_accident():
    # Even if someone misconfigures, an exact-list of addresses is the safe path;
    # here gmail.com is not in TRUSTED so a non-listed gmail is rejected.
    ok, _ = authenticate("random@gmail.com", [GMAIL_DKIM_PASS], ALLOW, TRUSTED)
    assert not ok


def test_forged_authserv_id_not_trusted():
    # Sender forges their own Authentication-Results with a non-receiver authserv-id.
    forged = "attacker.test; dkim=pass header.i=@gmail.com"
    ok, reason = authenticate("btucson1@gmail.com", [forged], ALLOW, TRUSTED)
    assert not ok and reason == "dkim_not_passed"


def test_real_gmail_result_among_forged_is_trusted():
    forged = "attacker.test; dkim=pass"
    real = "mx.google.com; dkim=pass; dmarc=pass"
    ok, reason = authenticate("btucson1@gmail.com", [forged, real], ALLOW, TRUSTED)
    assert ok and reason == "ok"


def test_auth_results_extracted_from_message():
    m = Message()
    m["From"] = "btucson1@gmail.com"
    m["Authentication-Results"] = GMAIL_DKIM_PASS
    results = auth_results_from_message(m)
    assert results == [GMAIL_DKIM_PASS]
    ok, _ = authenticate(m["From"], results, ALLOW, TRUSTED)
    assert ok
