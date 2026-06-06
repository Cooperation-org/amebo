"""
Tests for the reference_integrity claw.

Fully mocked — no DB, no live CRM/Taiga/abra. The service takes a
``BindingReader`` and a map of ``ReferenceResolver`` via constructor
injection, so tests supply fakes (same injection style as
test_goal_dispatcher / test_goal_scheduler, but DB-free because every port
is faked here).

Coverage:
- OK / DANGLING / UNRESOLVABLE classification.
- Empty binding set.
- Mixed set (one of each, plus a no-resolver kind and a non-external kind).
- Resolver-failure isolation: one resolver raising does not crash the run
  and only marks its own reference UNRESOLVABLE.
- Nothing is written anywhere: the fakes expose ONLY read methods, and a
  recording fake asserts no write/update/delete/send was ever called.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from src.services.reference_integrity import (
    IntegrityReport,
    ReferenceIntegrityService,
    RefStatus,
    run_reference_integrity_claw,
)


# ---------------------------------------------------------------------------
# Fakes (read-only by construction)
# ---------------------------------------------------------------------------

def _binding(
    binding_id: int,
    name: str,
    target_type: str,
    target_ref: str,
    scope: str = "linkedtrust",
    relationship: str = "LINKED_TO",
) -> Dict[str, Any]:
    return {
        "id": binding_id,
        "scope": scope,
        "name": name,
        "relationship": relationship,
        "target_type": target_type,
        "target_ref": target_ref,
    }


class FakeBindingReader:
    """
    Read-only fake of BindingReader. Holds bindings keyed by (name, scope).
    Records every read so tests can assert it was used. Exposes NO write
    method at all — a write attempt would be an AttributeError.
    """

    def __init__(self, bindings_by_name: Dict[str, List[Dict[str, Any]]]):
        self._by_name = bindings_by_name
        self.read_calls: List[tuple] = []

    def search_bindings_by_name(
        self,
        name: str,
        scope: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        self.read_calls.append((name, scope))
        return list(self._by_name.get(name, []))


class FakeResolver:
    """
    Read-only resolver fake. ``answers`` maps target_ref -> outcome
    (True/False/None). Unknown refs return None. Records reads; exposes no
    write surface. Optionally raises for a configured ref to exercise
    failure isolation.
    """

    def __init__(self, answers: Dict[str, Optional[bool]], raise_on: Optional[str] = None):
        self._answers = answers
        self._raise_on = raise_on
        self.exists_calls: List[str] = []

    def exists(self, ref: str) -> Optional[bool]:
        self.exists_calls.append(ref)
        if self._raise_on is not None and ref == self._raise_on:
            raise RuntimeError("system of record unreachable")
        return self._answers.get(ref)


class RecordingProbe:
    """
    A resolver that records every method name accessed on it via __getattr__,
    used to prove the service never invokes a write-shaped method. Only
    ``exists`` is implemented; any other attribute access is logged and
    raises so a stray write call would be caught loudly.
    """

    def __init__(self, outcome: Optional[bool]):
        self._outcome = outcome
        self.accessed: List[str] = []

    def exists(self, ref: str) -> Optional[bool]:
        self.accessed.append("exists")
        return self._outcome

    def __getattr__(self, item):  # pragma: no cover - defensive
        # Only triggered for attributes not defined above (e.g. write/update).
        object.__getattribute__(self, "accessed").append(item)
        raise AssertionError(f"reference_integrity invoked non-read method: {item!r}")


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

class TestClassification:
    def test_ok_when_target_exists(self):
        reader = FakeBindingReader({
            "Acme": [_binding(1, "Acme", "crm_contact", "42")],
        })
        resolvers = {"crm_contact": FakeResolver({"42": True})}
        svc = ReferenceIntegrityService(reader, resolvers)

        report = svc.check_scope("linkedtrust", ["Acme"])

        assert report.counts == {"total": 1, "ok": 1, "dangling": 0, "unresolvable": 0}
        assert report.ok[0].status is RefStatus.OK

    def test_dangling_when_target_missing(self):
        reader = FakeBindingReader({
            "Ghost": [_binding(2, "Ghost", "crm_contact", "999")],
        })
        resolvers = {"crm_contact": FakeResolver({"999": False})}
        svc = ReferenceIntegrityService(reader, resolvers)

        report = svc.check_scope("linkedtrust", ["Ghost"])

        assert report.counts["dangling"] == 1
        d = report.dangling[0]
        assert d.status is RefStatus.DANGLING
        # Enough detail to locate the dangling ref.
        assert d.binding_id == 2
        assert d.name == "Ghost"
        assert d.target_type == "crm_contact"
        assert d.target_ref == "999"

    def test_unresolvable_when_system_returns_none(self):
        reader = FakeBindingReader({
            "Maybe": [_binding(3, "Maybe", "taiga_task", "T-7")],
        })
        resolvers = {"taiga_task": FakeResolver({"T-7": None})}
        svc = ReferenceIntegrityService(reader, resolvers)

        report = svc.check_scope("linkedtrust", ["Maybe"])

        assert report.counts["unresolvable"] == 1
        assert report.unresolvable[0].status is RefStatus.UNRESOLVABLE

    def test_unresolvable_when_no_resolver_registered(self):
        reader = FakeBindingReader({
            "Orphan": [_binding(4, "Orphan", "crm_contact", "5")],
        })
        # No resolver for crm_contact at all.
        svc = ReferenceIntegrityService(reader, resolvers={})

        report = svc.check_scope("linkedtrust", ["Orphan"])

        assert report.counts["unresolvable"] == 1
        assert "no resolver registered" in report.unresolvable[0].detail

    def test_unresolvable_when_missing_target_ref(self):
        reader = FakeBindingReader({
            "Empty": [_binding(5, "Empty", "crm_contact", "")],
        })
        resolvers = {"crm_contact": FakeResolver({})}
        svc = ReferenceIntegrityService(reader, resolvers)

        report = svc.check_scope("linkedtrust", ["Empty"])

        assert report.counts["unresolvable"] == 1
        assert "no target_ref" in report.unresolvable[0].detail


# ---------------------------------------------------------------------------
# Empty / mixed / skipping
# ---------------------------------------------------------------------------

class TestSets:
    def test_empty_set(self):
        reader = FakeBindingReader({})
        svc = ReferenceIntegrityService(reader, resolvers={})
        report = svc.check_scope("linkedtrust", [])
        assert isinstance(report, IntegrityReport)
        assert report.counts == {"total": 0, "ok": 0, "dangling": 0, "unresolvable": 0}

    def test_names_with_no_bindings_yield_empty(self):
        reader = FakeBindingReader({})
        svc = ReferenceIntegrityService(reader, resolvers={})
        report = svc.check_scope("linkedtrust", ["nobody", "nothing"])
        assert report.total == 0
        # Reader was still consulted for each requested name.
        assert reader.read_calls == [("nobody", "linkedtrust"), ("nothing", "linkedtrust")]

    def test_non_external_target_types_are_skipped_not_flagged(self):
        # 'content' (amebo-internal) and 'uri' (claw pointer / external URL)
        # are not cross-system existence checks — they must be skipped, not
        # reported as anything.
        reader = FakeBindingReader({
            "Mixed": [
                _binding(10, "Mixed", "content", "1234"),
                _binding(11, "Mixed", "uri", "amebo:claw/abc"),
                _binding(12, "Mixed", "crm_contact", "42"),
            ],
        })
        resolvers = {"crm_contact": FakeResolver({"42": True})}
        svc = ReferenceIntegrityService(reader, resolvers)

        report = svc.check_scope("linkedtrust", ["Mixed"])

        # Only the crm_contact binding is examined.
        assert report.total == 1
        assert report.ok[0].target_type == "crm_contact"

    def test_mixed_set_classifies_each(self):
        reader = FakeBindingReader({
            "A": [_binding(20, "A", "crm_contact", "ok-1")],
            "B": [_binding(21, "B", "crm_contact", "gone-1")],
            "C": [_binding(22, "C", "taiga_task", "maybe-1")],
            "D": [_binding(23, "D", "github_pr", "no-resolver")],  # external, no resolver
            "E": [_binding(24, "E", "content", "internal")],       # not external -> skipped
        })
        resolvers = {
            "crm_contact": FakeResolver({"ok-1": True, "gone-1": False}),
            "taiga_task": FakeResolver({"maybe-1": None}),
        }
        # github_pr is declared external (so a missing resolver is reported,
        # not silently skipped); content stays non-external.
        svc = ReferenceIntegrityService(
            reader, resolvers,
            external_types=("crm_contact", "taiga_task", "github_pr"),
        )

        report = svc.check_scope("linkedtrust", ["A", "B", "C", "D", "E"])

        # E (content) skipped; A ok, B dangling, C + D unresolvable.
        assert report.counts == {"total": 4, "ok": 1, "dangling": 1, "unresolvable": 2}
        assert {c.name for c in report.dangling} == {"B"}
        assert {c.name for c in report.unresolvable} == {"C", "D"}

    def test_duplicate_bindings_deduped(self):
        same = _binding(30, "Dup", "crm_contact", "42")
        reader = FakeBindingReader({"Dup": [same, dict(same)]})
        resolvers = {"crm_contact": FakeResolver({"42": True})}
        svc = ReferenceIntegrityService(reader, resolvers)

        report = svc.check_scope("linkedtrust", ["Dup", "Dup"])
        assert report.total == 1


# ---------------------------------------------------------------------------
# Failure isolation
# ---------------------------------------------------------------------------

class TestFailureIsolation:
    def test_one_resolver_raising_does_not_crash_run(self):
        reader = FakeBindingReader({
            "Up": [_binding(40, "Up", "crm_contact", "ok-1")],
            "Down": [_binding(41, "Down", "taiga_task", "boom")],
            "AlsoUp": [_binding(42, "AlsoUp", "crm_contact", "ok-2")],
        })
        resolvers = {
            "crm_contact": FakeResolver({"ok-1": True, "ok-2": True}),
            "taiga_task": FakeResolver({}, raise_on="boom"),  # raises
        }
        svc = ReferenceIntegrityService(reader, resolvers)

        report = svc.check_scope("linkedtrust", ["Up", "Down", "AlsoUp"])

        # The raising resolver isolates to its own reference.
        assert report.counts == {"total": 3, "ok": 2, "dangling": 0, "unresolvable": 1}
        bad = report.unresolvable[0]
        assert bad.name == "Down"
        assert "resolver error" in bad.detail

    def test_reader_failure_for_one_name_isolated(self):
        class FlakyReader(FakeBindingReader):
            def search_bindings_by_name(self, name, scope=None, workspace_id=None):
                if name == "explodes":
                    raise RuntimeError("store unavailable")
                return super().search_bindings_by_name(name, scope, workspace_id)

        reader = FlakyReader({"good": [_binding(50, "good", "crm_contact", "ok-1")]})
        resolvers = {"crm_contact": FakeResolver({"ok-1": True})}
        svc = ReferenceIntegrityService(reader, resolvers)

        report = svc.check_scope("linkedtrust", ["explodes", "good"])
        # The good name still resolves; the failing one contributes nothing.
        assert report.counts == {"total": 1, "ok": 1, "dangling": 0, "unresolvable": 0}


# ---------------------------------------------------------------------------
# Read-only guarantee
# ---------------------------------------------------------------------------

class TestReadOnly:
    def test_resolver_only_read_method_invoked(self):
        reader = FakeBindingReader({
            "X": [_binding(60, "X", "crm_contact", "42")],
        })
        probe = RecordingProbe(outcome=True)
        svc = ReferenceIntegrityService(reader, resolvers={"crm_contact": probe})

        report = svc.check_scope("linkedtrust", ["X"])

        assert report.counts["ok"] == 1
        # Only 'exists' was ever touched on the resolver — no write-shaped call.
        assert probe.accessed == ["exists"]

    def test_reader_exposes_no_write_method(self):
        reader = FakeBindingReader({})
        # The read-only port has no write/update/delete attribute.
        for forbidden in ("create_binding", "set_status", "delete", "write",
                          "update", "append_event", "commit"):
            assert not hasattr(reader, forbidden)

    def test_report_to_dict_is_serializable_and_has_locators(self):
        reader = FakeBindingReader({
            "Ghost": [_binding(70, "Ghost", "crm_contact", "999")],
        })
        resolvers = {"crm_contact": FakeResolver({"999": False})}
        svc = ReferenceIntegrityService(reader, resolvers)

        d = svc.check_scope("linkedtrust", ["Ghost"]).to_dict()
        assert d["counts"]["dangling"] == 1
        loc = d["dangling"][0]
        assert loc["binding_id"] == 70
        assert loc["target_ref"] == "999"
        assert loc["status"] == "DANGLING"


# ---------------------------------------------------------------------------
# Claw entry point
# ---------------------------------------------------------------------------

class TestClawEntryPoint:
    def test_entry_point_returns_report_with_injected_ports(self):
        reader = FakeBindingReader({
            "Acme": [_binding(80, "Acme", "crm_contact", "42")],
            "Ghost": [_binding(81, "Ghost", "crm_contact", "999")],
        })
        resolvers = {"crm_contact": FakeResolver({"42": True, "999": False})}

        report = run_reference_integrity_claw(
            scope="linkedtrust",
            names=["Acme", "Ghost"],
            reader=reader,
            resolvers=resolvers,
        )
        assert isinstance(report, IntegrityReport)
        assert report.counts == {"total": 2, "ok": 1, "dangling": 1, "unresolvable": 0}


# ---------------------------------------------------------------------------
# Adapters (CLI-backed resolvers) — fake the CLI runner, never shell out
# ---------------------------------------------------------------------------

class TestAdapters:
    def _runner_recording(self):
        calls = []

        def runner(command, args="", timeout=10):
            calls.append((command, args))
            return "not found"

        return runner, calls

    def test_odoo_resolver_uses_readonly_show_command(self):
        from src.services.reference_integrity_adapters import OdooContactResolver

        runner, calls = self._runner_recording()
        r = OdooContactResolver(cli_runner=runner)
        outcome = r.exists("42")

        assert outcome is False  # "not found" parses as DANGLING
        assert calls and calls[0][0] == "odoo-cli"
        # Read-only: only a 'show' read subcommand, no write verbs.
        sent = calls[0][1].lower()
        assert sent.startswith("show ")
        for write_verb in ("create", "update", "write", "delete", "unlink", "set ", "add "):
            assert write_verb not in sent

    def test_taiga_resolver_uses_readonly_show_command(self):
        from src.services.reference_integrity_adapters import TaigaTaskResolver

        runner, calls = self._runner_recording()
        r = TaigaTaskResolver(cli_runner=runner)
        outcome = r.exists("T-7")

        assert outcome is False
        assert calls and calls[0][0] == "mcp-taiga"
        sent = calls[0][1].lower()
        assert sent.startswith("show ")
        for write_verb in ("create", "update", "write", "delete", "set ", "add "):
            assert write_verb not in sent

    def test_looks_missing_interpretation(self):
        from src.services.reference_integrity_adapters import _looks_missing

        assert _looks_missing("Contact not found") is False
        assert _looks_missing("does not exist") is False
        assert _looks_missing("Error: boom") is None
        assert _looks_missing("Tool 'odoo-cli' not found in PATH") is None
        assert _looks_missing("Command timed out after 10s") is None
        assert _looks_missing("") is None
        # Ambiguous non-error output stays UNRESOLVABLE (no false OK).
        assert _looks_missing("some record dump") is None

    def test_resolver_cli_failure_is_unresolvable(self):
        from src.services.reference_integrity_adapters import OdooContactResolver

        def boom(command, args="", timeout=10):
            raise RuntimeError("subprocess blew up")

        r = OdooContactResolver(cli_runner=boom)
        assert r.exists("42") is None
