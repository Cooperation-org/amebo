#!/usr/bin/env python3
"""Hard guardrails for Claude sessions in this repo.

Blocks the actions sessions must never take, regardless of what the model
was told or talked into. Updated 2026-07-04 for Golda's work-directly-in-live
model (single session, commits straight to main in the live checkout):
push/merge on main are ALLOWED; force-push, git stash, and touching
non-amebo services remain hard-blocked.
Exit 2 blocks the tool call; the stderr message is shown to the model.
"""
import json
import re
import sys


def block(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(2)


def main() -> None:
    data = json.load(sys.stdin)
    if data.get("tool_name") != "Bash":
        sys.exit(0)
    cmd = data.get("tool_input", {}).get("command", "")

    if re.search(r"\bgit\s+stash\b", cmd):
        block("git stash is forbidden (house rule). Commit to a WIP branch instead.")

    if re.search(r"\bgit\s+push\b.*(\s--force\b|\s-f\b|\+\S*:)", cmd):
        block("Force push is forbidden.")

    # systemctl: amebo's own services only (this is a shared VM).
    m = re.search(r"\bsystemctl\b\s+(?:--\S+\s+)*(\w[\w-]*)\s+(\S+)", cmd)
    if m and m.group(1) not in ("status", "show", "list-units", "list-timers",
                                "is-active", "is-enabled", "cat", "daemon-reload"):
        unit = m.group(2)
        if not re.match(r"^(tmp-)?amebo[\w.-]*$", unit):
            block(f"systemctl {m.group(1)} on '{unit}' is forbidden: only amebo-* services "
                  "may be managed from amebo sessions (shared VM).")

    if "--dangerously-skip-permissions" in cmd:
        block("Nested dangerously-skip-permissions sessions are forbidden.")

    sys.exit(0)


if __name__ == "__main__":
    main()
