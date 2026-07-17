"""
Personal amebo REPL — piece 1 of "personal amebo".

A conversational amebo you launch in your own shell, running as YOU. It's an
ordinary amebo instance/loop (same qa path, same registry, same gates) with one
extra: a general `shell` tool, registered only because this process is a verified
personal session (see shell_tool.register_shell_tool_if_personal). Read-only
commands auto-run; anything else asks you to confirm right here in the terminal.

This is the in-process REPL. The phone path (piece 2) makes the same session
consumable over a thread via LISTEN/NOTIFY — same turn/event shapes.

Run (as the owner uid):
    AMEBO_PERSONAL_MODE=1 AMEBO_PERSONAL_UID=$(id -u) python -m src.personal.repl
"""

from __future__ import annotations

import os
import sys

SYSTEM = (
    "You are amebo, running as this person's PERSONAL assistant in their own "
    "shell session, as them. You can run shell commands with the `shell` tool "
    "(read-only commands run immediately; anything else asks them to confirm). "
    "You also have amebo's read tools (projects, knowledge). Think a lot, work a "
    "lot, speak little — be concise and concrete, like a capable colleague. When "
    "a task needs commands, just use the shell tool."
)

# The personal session's tool set: shell + amebo's safe read tools.
_PERSONAL_TOOLS = [
    "shell", "list_projects", "read_main_md", "search_knowledge_base",
    "abra_search", "lookup_contact",
]


def _terminal_confirm(command: str) -> bool:
    try:
        ans = input(f"\n  ⚠ run a non-read command?\n    $ {command}\n  [y/N] ").strip().lower()
    except EOFError:
        return False
    return ans in ("y", "yes")


def run_repl(in_stream=None, out=print) -> int:
    from src.tools.shell_tool import register_shell_tool_if_personal
    registered = register_shell_tool_if_personal()
    from src.tools.registry import get_tool, _tool_to_schema, trust_gate
    from src.services.org_context import OrgContext
    from src.services.trust import Principal

    if not registered:
        out("⚠ personal shell NOT available — set AMEBO_PERSONAL_MODE=1 and run "
            "as AMEBO_PERSONAL_UID. Continuing with read tools only.")

    org_id = int(os.getenv("AMEBO_PERSONAL_ORG_ID", "1"))
    instance_id = int(os.getenv("AMEBO_PERSONAL_INSTANCE_ID", "1"))
    person_id = int(os.getenv("AMEBO_PERSONAL_PERSON_ID", "0")) or None
    ctx = OrgContext(org_id=org_id, instance_id=instance_id, actor_type="user",
                     actor_person_id=person_id, authority="service")
    # This session is verified-personal: it only started because os.getuid()
    # matched the declared owner (shell_tool's guard). That uid check IS the
    # auth, so the principal is SERVICE-trust — the owner on their own box.
    principal = Principal(transport="cli", person_id=person_id, is_service=True)

    tools = [_tool_to_schema(get_tool(n)) for n in _PERSONAL_TOOLS if get_tool(n)]

    from src.services.llm_client import get_llm_client, resolve_model
    client = get_llm_client()
    if client is None:
        out("No LLM API key configured."); return 1
    model = resolve_model(os.getenv("AMEBO_QA_MODEL", "claude-sonnet-4-6"))

    reader = in_stream or sys.stdin
    out("amebo personal — type 'exit' to quit. Shell: "
        + ("ON" if registered else "off"))
    messages = []
    while True:
        out("", end="") if False else None
        try:
            line = (input("\nyou › ") if reader is sys.stdin else reader.readline())
        except EOFError:
            break
        if not line and reader is not sys.stdin:
            break
        user = line.strip()
        if user in ("exit", "quit"):
            break
        if not user:
            continue
        messages.append({"role": "user", "content": user})

        for _round in range(8):
            resp = client.messages.create(model=model, max_tokens=2000,
                                          system=SYSTEM, messages=messages, tools=tools)
            # Convert SDK content blocks to plain dicts before feeding back
            # (raw blocks can hit an SDK re-serialization bug).
            assistant_content = []
            for b in resp.content:
                if b.type == "text":
                    assistant_content.append({"type": "text", "text": b.text})
                elif b.type == "tool_use":
                    assistant_content.append({"type": "tool_use", "id": b.id,
                                              "name": b.name, "input": b.input})
            messages.append({"role": "assistant", "content": assistant_content})
            if resp.stop_reason != "tool_use":
                text = "".join(b.text for b in resp.content if b.type == "text")
                out(f"\namebo › {text.strip()}")
                break
            results = []
            tctx = {"org_context": ctx, "org_id": org_id, "confirm": _terminal_confirm}
            for b in resp.content:
                if b.type != "tool_use":
                    continue
                tool = get_tool(b.name)
                if tool is None:
                    res = f"Unknown tool: {b.name}"
                else:
                    denial = trust_gate(tool, principal)
                    res = denial if denial else (tool.execute(b.input, tctx) or "")
                out(f"  · {b.name} {dict(b.input)} →\n{_indent(res)}")
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": res})
            messages.append({"role": "user", "content": results})
    out("bye.")
    return 0


def _indent(s: str, n: int = 4) -> str:
    pad = " " * n
    return "\n".join(pad + ln for ln in str(s).splitlines()[:40])


if __name__ == "__main__":
    sys.exit(run_repl())
