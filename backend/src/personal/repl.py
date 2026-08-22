"""
Personal amebo REPL — piece 1 of "personal amebo".

A conversational amebo you launch in your own shell, running as YOU. Same
conversation core as the Slack/qa path: it reuses ConversationManager, so it
gets the SAME context management Claude Code has —

  - stable system prefix (identity + rules), never per-turn volatile data, so
    the cached prefix hash matches call-to-call and the server-side prompt
    cache hits;
  - `cache_control` on the system block plus a rolling breakpoint on the last
    message, so each tool round's growing prefix is cached too;
  - turns persisted verbatim to the thread, so the next turn's prefix is
    byte-identical to what was cached;
  - compaction/summary of old turns past the token threshold.

Plus one extra: a general `shell` tool, registered only because this process
is a verified personal session (see shell_tool.register_shell_tool_if_personal).
Read-only commands auto-run; anything else asks you to confirm in the terminal.

Model and provider are NOT coupled to this mode. The loop runs whatever
provider/model is configured; override for this process only via
AMEBO_CLI_PROVIDER / AMEBO_CLI_MODEL without touching the running services.

Run (as the owner uid):
    AMEBO_PERSONAL_MODE=1 AMEBO_PERSONAL_UID=$(id -u) python -m src.personal.repl
"""

from __future__ import annotations

import os
import sys
from typing import Dict, List, Tuple

# A constant note appended to the instance identity so the model knows the shell
# tool exists. MUST be constant — anything per-turn here would change the system
# block and bust the prefix cache on every call.
_SHELL_NOTE = (
    "\n\nYou are running as this person's PERSONAL assistant in their own shell "
    "session, as them. You can run shell commands with the `shell` tool "
    "(read-only commands run immediately; anything else asks them to confirm). "
    "Think a lot, work a lot, speak little — concise and concrete, like a "
    "capable colleague. When a task needs commands, just use the shell tool."
)

# The personal session's tool set: shell + amebo's safe read tools.
_PERSONAL_TOOLS = [
    "shell", "list_projects", "read_main_md", "search_knowledge_base",
    "abra_search", "lookup_contact", "web_search", "web_research",
]

# Tool rounds allowed within a single turn before we force an answer.
_MAX_TOOL_ROUNDS = int(os.getenv("AMEBO_CLI_MAX_TOOL_ROUNDS", "16"))
_MAX_TOKENS = int(os.getenv("AMEBO_CLI_MAX_TOKENS", "4000"))


def _terminal_confirm(command: str) -> bool:
    try:
        ans = input(f"\n  ⚠ run a non-read command?\n    $ {command}\n  [y/N] ").strip().lower()
    except EOFError:
        return False
    return ans in ("y", "yes")


def _cache_prefix(
    system_prompt: str, messages: List[Dict]
) -> Tuple[List[Dict], List[Dict]]:
    """Attach prompt-cache breakpoints: the system block (stable per thread) and
    a rolling breakpoint on the LAST message's last content block.

    The rolling last-message breakpoint means every growing prefix — prior turns
    across the session AND the tool rounds within this turn — becomes cacheable.
    The server picks the longest matching prefix, so as long as history is sent
    byte-identically (it is: turns are persisted verbatim, system carries no
    per-turn data) the cache hits. Only text and tool_result blocks carry
    cache_control; a trailing tool_use block is never marked.
    """
    system_blocks = [{
        "type": "text",
        "text": system_prompt,
        "cache_control": {"type": "ephemeral"},
    }]

    out_msgs: List[Dict] = []
    last = len(messages) - 1
    for i, msg in enumerate(messages):
        content = msg["content"]
        if i != last:
            out_msgs.append({"role": msg["role"], "content": content})
            continue
        # Mark the last content block of the last message.
        if isinstance(content, str):
            blocks = [{
                "type": "text", "text": content,
                "cache_control": {"type": "ephemeral"},
            }]
        else:
            blocks = [dict(b) for b in content]
            if blocks and blocks[-1].get("type") in ("text", "tool_result"):
                blocks[-1] = {**blocks[-1], "cache_control": {"type": "ephemeral"}}
        out_msgs.append({"role": msg["role"], "content": blocks})
    return system_blocks, out_msgs


def _serialize_blocks(content) -> List[Dict]:
    """SDK content blocks -> plain dicts, so the next request re-serializes them
    identically (raw SDK blocks can hit a re-serialization bug and shift bytes)."""
    out = []
    for b in content:
        if b.type == "text":
            out.append({"type": "text", "text": b.text})
        elif b.type == "tool_use":
            out.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
    return out


def _run_turn(client, model, system_prompt, messages, tools, tctx, principal, out) -> str:
    """One user turn: call the model, run tool rounds, return the final text.
    `messages` is the full history+question from ConversationManager.build_messages;
    tool-round scaffolding stays local and is NOT persisted (only the final answer
    is), keeping the cross-turn prefix clean and byte-stable."""
    from src.tools.registry import get_tool, trust_gate

    work = list(messages)
    for _round in range(_MAX_TOOL_ROUNDS + 1):
        system_blocks, cached = _cache_prefix(system_prompt, work)
        kwargs = dict(model=model, max_tokens=_MAX_TOKENS,
                      system=system_blocks, messages=cached)
        if tools:
            kwargs["tools"] = tools
        # Last round: force an answer instead of another tool call.
        if _round == _MAX_TOOL_ROUNDS and tools:
            kwargs["tool_choice"] = {"type": "none"}
        resp = client.messages.create(**kwargs)

        work.append({"role": "assistant", "content": _serialize_blocks(resp.content)})
        if resp.stop_reason != "tool_use":
            return "".join(b.text for b in resp.content if b.type == "text").strip()

        results = []
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
        work.append({"role": "user", "content": results})
    return "(no answer)"


def run_repl(in_stream=None, out=print) -> int:
    # Provider/model are config, decoupled from this mode. Override for THIS
    # process only; the Slack service keeps whatever it was started with.
    if os.getenv("AMEBO_CLI_PROVIDER"):
        os.environ["AMEBO_LLM_PROVIDER"] = os.environ["AMEBO_CLI_PROVIDER"]

    from src.tools.shell_tool import register_shell_tool_if_personal
    registered = register_shell_tool_if_personal()
    from src.tools.registry import get_tool, _tool_to_schema
    from src.services.org_context import OrgContext
    from src.services.trust import Principal
    from src.services.conversation_manager import ConversationManager
    from src.services.llm_client import get_llm_client, resolve_model

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

    client = get_llm_client()
    if client is None:
        out("No LLM client — the configured provider's API key is not set "
            "(ANTHROPIC_API_KEY for anthropic, MINIMAX_API_KEY for minimax).")
        return 1
    # Model: CLI override > standard QA model > default. resolve_model maps it
    # onto whatever the active provider actually serves.
    model = resolve_model(
        os.getenv("AMEBO_CLI_MODEL") or os.getenv("AMEBO_QA_MODEL", "claude-sonnet-4-6")
    )

    # Persistent thread → history is stored verbatim and replayed byte-identically
    # each turn, which is what makes the prefix cache hit. Reuse a session name to
    # resume (and keep compaction state); default is per-process.
    session = os.getenv("AMEBO_CLI_SESSION") or f"cli-{os.getuid()}-{os.getpid()}"
    mgr = ConversationManager(
        source_type="cli", source_ref=session,
        instance_slug=os.getenv("AMEBO_CLI_INSTANCE", "whatscookin"),
    )
    base_system = mgr.get_system_prompt() + _SHELL_NOTE

    reader = in_stream or sys.stdin
    out(f"amebo personal — {model} — session {session} — 'exit' to quit. "
        f"Shell: {'ON' if registered else 'off'}")

    tctx = {"org_context": ctx, "org_id": org_id, "confirm": _terminal_confirm}
    while True:
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

        # build_messages gives system(identity+rules) + persisted history + this
        # question, with NO per-turn knowledge stuffed in (knowledge_context="")
        # so the system prefix stays byte-stable and cacheable; tools fetch what
        # the model needs instead.
        system_prompt, messages = mgr.build_messages(new_question=user, knowledge_context="")
        system_prompt = system_prompt + _SHELL_NOTE
        answer = _run_turn(client, model, system_prompt, messages, tools, tctx, principal, out)
        out(f"\namebo › {answer}")
        # Persist only the clean question/answer pair (not tool scaffolding) and
        # compact if over threshold.
        mgr.add_exchange(user, answer)
    out("bye.")
    return 0


def _indent(s: str, n: int = 4) -> str:
    pad = " " * n
    return "\n".join(pad + ln for ln in str(s).splitlines()[:40])


if __name__ == "__main__":
    sys.exit(run_repl())
