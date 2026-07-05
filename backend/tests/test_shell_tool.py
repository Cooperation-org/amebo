"""Personal-session shell tool: read-only auto-runs, else confirm; registered
only in a verified personal session (never hosted, never config)."""
from __future__ import annotations
import os
import pytest
from src.tools import shell_tool
from src.tools.shell_tool import _is_readonly, shell_impl, register_shell_tool_if_personal


class TestReadonlyClassification:
    @pytest.mark.parametrize("cmd", [
        "ls -la", "cat foo.txt", "git status", "git log --oneline -5",
        "rg TODO src", "pwd", "git diff HEAD~1", "git -C /some/repo log --oneline", "git -c x=y status",
    ])
    def test_readonly(self, cmd):
        assert _is_readonly(cmd) is True

    @pytest.mark.parametrize("cmd", [
        "rm -rf /tmp/x", "git push", "git commit -m x", "echo hi > f",
        "cat a | tee b", "ls; rm x", "python foo.py", "mv a b",
        "git status && rm x",     # metachar hides a write
    ])
    def test_not_readonly(self, cmd):
        assert _is_readonly(cmd) is False


class TestShellExec:
    def test_readonly_autoruns_without_confirm(self):
        out = shell_impl({"command": "echo hello-personal"}, {})
        assert "hello-personal" in out

    def test_nonreadonly_refused_without_confirm(self):
        ran = shell_impl({"command": "touch /tmp/should-not-exist-xyz"}, {})
        assert "Refused" in ran and not os.path.exists("/tmp/should-not-exist-xyz")

    def test_nonreadonly_declined(self):
        out = shell_impl({"command": "rm -rf /tmp/xyz"}, {"confirm": lambda c: False})
        assert "Declined" in out

    def test_nonreadonly_runs_when_confirmed(self, tmp_path):
        f = tmp_path / "made-by-shell"
        seen = {}
        out = shell_impl({"command": f"touch {f}"},
                         {"confirm": lambda c: seen.setdefault("cmd", c) or True})
        assert f.exists() and seen["cmd"].startswith("touch")

    def test_timeout(self):
        shell_tool.SHELL_TIMEOUT_S = 1
        try:
            out = shell_impl({"command": "sleep 3"}, {"confirm": lambda c: True})
            assert "timed out" in out
        finally:
            shell_tool.SHELL_TIMEOUT_S = 60

    def test_output_truncated(self):
        out = shell_impl({"command": "seq 1 100000"}, {"confirm": lambda c: True})
        assert "truncated" in out


class TestRegistrationGuard:
    def _clear(self, monkeypatch):
        for k in ("AMEBO_PERSONAL_MODE", "AMEBO_PERSONAL_UID", "AMEBO_SERVICE_UID"):
            monkeypatch.delenv(k, raising=False)

    def test_not_registered_without_personal_mode(self, monkeypatch):
        self._clear(monkeypatch)
        assert register_shell_tool_if_personal() is False

    def test_not_registered_when_uid_mismatch(self, monkeypatch):
        self._clear(monkeypatch)
        monkeypatch.setenv("AMEBO_PERSONAL_MODE", "1")
        monkeypatch.setenv("AMEBO_PERSONAL_UID", str(os.getuid() + 12345))  # not us
        assert register_shell_tool_if_personal() is False

    def test_registers_when_personal_and_uid_matches(self, monkeypatch):
        self._clear(monkeypatch)
        monkeypatch.setenv("AMEBO_PERSONAL_MODE", "1")
        monkeypatch.setenv("AMEBO_PERSONAL_UID", str(os.getuid()))
        try:
            assert register_shell_tool_if_personal() is True
            from src.tools.registry import get_tool
            assert get_tool("shell") is not None
            assert get_tool("shell").effective_access_class == "admin"
        finally:
            from src.tools import registry
            registry._TOOLS.pop("shell", None)  # don't leak into other tests

    def test_refuses_service_uid(self, monkeypatch):
        self._clear(monkeypatch)
        monkeypatch.setenv("AMEBO_PERSONAL_MODE", "1")
        monkeypatch.setenv("AMEBO_PERSONAL_UID", str(os.getuid()))
        monkeypatch.setenv("AMEBO_SERVICE_UID", str(os.getuid()))  # we ARE the service uid
        assert register_shell_tool_if_personal() is False
