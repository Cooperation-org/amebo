"""
Goal dispatcher — the claw.

Thin wrapper that pursues a single goal using amebo's existing model + tool
plumbing. Stays out of the core Q&A path. Disabling the goal subsystem is
just a config flag elsewhere; the dispatcher is only invoked from the
scheduler when that flag is enabled.

Responsibilities:
- Load the goal + the org's instance + the org's semantic context (vision,
  values, current context) from abra.
- Frame the task for Claude as "pursue this goal" rather than "answer a
  question".
- Run a bounded agentic loop, recording each tool call as a goal_event.
- On success / failure, transition the goal through GoalEngine (which also
  writes the appropriate event).
- Post a notification to the configured channel.

Boundaries:
- Channel adapters (slack/email/etc.) are pluggable. The dispatcher never
  imports a channel directly — it asks a registry for the right adapter.
- The Anthropic client is injected so tests can replace it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.credentials import (
    CredentialExpired,
    CredentialMissing,
    CredentialRevoked,
    mint_connect_link,
)
from src.db.repositories.binding_repo import BindingRepo
from src.db.repositories.goal_repo import GoalRepo
from src.db.repositories.instance_repo import InstanceRepo
from src.services.goal_engine import (
    GoalEngine, GoalNotFoundError, InvalidTransitionError,
)
from src.services.goal_guardrails import GuardrailContext, GuardrailTripped
from src.services.draft_approval_service import DraftApprovalService
from src.services.human_output_gate import (
    HumanOutputGate, Disposition, register_output_gate_gc,
)

logger = logging.getLogger(__name__)


# Public base URL used when minting a connect link surfaced through a
# channel. Read inside _make_connect_url so tests can override the env.


def _make_connect_url(short_code: str) -> str:
    import os
    base = os.getenv("AMEBO_PUBLIC_URL", "http://localhost:8000").rstrip("/")
    return f"{base}/connect/{short_code}"


# Bound the agentic loop so a misbehaving model cannot run forever.
MAX_TOOL_ROUNDS = 5
DEFAULT_MAX_TOKENS = 2000


@dataclass
class DispatchResult:
    """Outcome of dispatching a single goal."""

    goal_id: str
    status: str                    # 'completed' | 'failed' | 'skipped'
    summary: Optional[str] = None
    tool_rounds: int = 0
    notification_sent: bool = False
    error: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)


# A notifier takes (channel_spec, message_text) and returns True on success.
Notifier = Callable[[str, str], bool]


def _default_notifier(channel: str, message: str) -> bool:
    """
    Fallback notifier: log it. Channel-specific adapters (Slack, email,
    etc.) plug in at GoalDispatcher construction time.
    """
    logger.info("[goal-notify] %s :: %s", channel, message)
    return True


def _is_recurring(goal: Dict[str, Any]) -> bool:
    """
    True if the goal's trigger fires repeatedly (a cron schedule). Recurring
    goals re-arm to pending after each dispatch cycle instead of completing
    terminally, so the scheduler runs them again on the next cron edge. One-
    shot goals (manual / event / unspecified trigger) complete and retire.

    Mirrors the cron branch of GoalScheduler._should_fire: a cron trigger is
    only "recurring" once it actually carries an expression.
    """
    cfg = goal.get("trigger_config") or {}
    return (cfg.get("type") or "").lower() == "cron" and bool(cfg.get("expression"))


class GoalDispatcher:
    """
    A dispatcher instance is cheap. It holds repositories and an optional
    Anthropic client + notifier. All long-lived resources are pooled at the
    DB connection layer, not here.
    """

    def __init__(
        self,
        goal_repo: Optional[GoalRepo] = None,
        engine: Optional[GoalEngine] = None,
        instance_repo: Optional[InstanceRepo] = None,
        anthropic_client: Optional[Any] = None,
        notifier: Optional[Notifier] = None,
    ):
        self._goal_repo = goal_repo or GoalRepo()
        self._engine = engine or GoalEngine(self._goal_repo)
        self._instance_repo = instance_repo or InstanceRepo()
        self._client = anthropic_client          # may be None in tests

        # Human-output (noise) gate: wrap the raw notifier so the claw's own
        # status messages are deduped / thread-preferred / rate-limited /
        # batched before they reach a human (docs/OUTPUT_GATE.md). The raw
        # notifier is kept for the draft-approval gate's "approval needed"
        # notices, which must always go out and not be batched/suppressed.
        raw_notifier = notifier or _default_notifier
        self._raw_notify = raw_notifier
        self._output_gate = HumanOutputGate()
        register_output_gate_gc(self._output_gate)

        def _gated_notify(channel: str, message: str) -> bool:
            decision = self._output_gate.gate(message, channel=channel)
            if decision.disposition is Disposition.SEND:
                return bool(raw_notifier(channel, decision.text or message))
            # DEFER → queued for the daily stand-up; SUPPRESS → duplicate/noise.
            return True

        self._notify = _gated_notify

        # Draft-approval gate: outbound/destructive tool calls are held for
        # human approval before they execute (docs/DRAFT_APPROVAL_GATE.md).
        # Approval notices use the raw notifier so they are never suppressed.
        self._draft_gate = DraftApprovalService(notifier=raw_notifier)

    # ----------------------------------------------------------------- API

    def dispatch(self, goal_id: str) -> DispatchResult:
        """
        Pursue a single goal end-to-end. Idempotent against terminal states:
        re-dispatching a completed goal returns a 'skipped' result.
        """
        try:
            goal = self._engine.get(goal_id)
        except GoalNotFoundError:
            return DispatchResult(goal_id=goal_id, status="failed",
                                  error=f"Goal not found: {goal_id}")

        if goal["status"] in ("completed", "failed"):
            return DispatchResult(goal_id=goal_id, status="skipped",
                                  summary=f"already {goal['status']}")

        # Activate (idempotent — returns None if someone beat us to it).
        if goal["status"] == "pending":
            activated = self._engine.activate(goal_id, actor_type="claw")
            if activated is None:
                # Another worker already picked it up.
                return DispatchResult(goal_id=goal_id, status="skipped",
                                      summary="already activated by another worker")

        # Build context and pursue.
        try:
            org_context = self._load_org_context(goal["org_id"])
            instance = self._load_instance(goal["org_id"])
            summary, tool_calls = self._pursue(goal, instance, org_context)
        except (CredentialMissing, CredentialExpired, CredentialRevoked) as exc:
            return self._block_on_credential(goal, exc)
        except GuardrailTripped as exc:
            logger.warning("Goal %s tripped guardrail %s: %s",
                           goal_id, exc.which, exc.reason)
            try:
                self._goal_repo.append_event(
                    goal_id=goal_id,
                    actor_type="claw",
                    action=f"guardrail_trip:{exc.which}",
                    result_summary=exc.reason,
                    metadata=exc.metadata,
                )
            except Exception:
                logger.exception("Failed to record guardrail event")
            try:
                self._engine.fail(goal_id, reason=f"guardrail:{exc.which}: {exc.reason}")
            except InvalidTransitionError:
                pass
            return DispatchResult(
                goal_id=goal_id, status="failed",
                error=f"guardrail:{exc.which}",
                summary=exc.reason,
            )
        except Exception as exc:
            logger.exception("Goal %s dispatch raised", goal_id)
            try:
                self._engine.fail(goal_id, reason=str(exc))
            except InvalidTransitionError:
                pass  # goal is already terminal
            return DispatchResult(goal_id=goal_id, status="failed", error=str(exc))

        # Finish the cycle, then notify. Recurring (cron) goals re-arm to
        # pending so the scheduler runs them again on the next cron edge;
        # one-shot goals complete terminally.
        if _is_recurring(goal):
            self._engine.rearm(goal_id, summary=summary)
        else:
            self._engine.complete(goal_id, summary=summary)
        notification_sent = self._maybe_notify(goal, summary)

        return DispatchResult(
            goal_id=goal_id,
            status="completed",
            summary=summary,
            tool_rounds=len(tool_calls),
            tool_calls=tool_calls,
            notification_sent=notification_sent,
        )

    # ------------------------------------------------------------- Context

    def _load_primary_workspace_id(self, org_id: int) -> Optional[str]:
        """
        Return the org's primary Slack workspace_id (or the first one
        linked) so tools that need workspace isolation (semantic search,
        slack ingestion) can be scoped.
        """
        from src.db.connection import DatabaseConnection
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT workspace_id FROM org_workspaces "
                    "WHERE org_id = %s "
                    "ORDER BY is_primary DESC, added_at ASC "
                    "LIMIT 1",
                    (org_id,),
                )
                row = cur.fetchone()
                return row[0] if row else None
        finally:
            DatabaseConnection.return_connection(conn)

    def _load_instance(self, org_id: int) -> Optional[Dict[str, Any]]:
        """First instance for this org, if any. Returns None when missing."""
        # Stable lookup via a one-off query rather than adding a new repo
        # method just for this. If we need this elsewhere, lift it up.
        from src.db.connection import DatabaseConnection
        from psycopg2 import extras as pg_extras

        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=pg_extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM instances WHERE org_id = %s "
                    "ORDER BY created_at ASC LIMIT 1",
                    (org_id,),
                )
                row = cur.fetchone()
                return dict(row) if row else None
        finally:
            DatabaseConnection.return_connection(conn)

    def _load_org_context(self, org_id: int) -> Dict[str, List[str]]:
        """
        Load the org's semantic context from abra: vision, values, and any
        currently-hot context. Returned as plain strings per category so
        the dispatcher can decide how to compose them into the prompt.

        Keys returned:
            vision      — list of vision content blobs
            values      — list of values content blobs
            current     — list of currently hot context content blobs

        Empty lists when nothing is stored, so callers can compose without
        special-casing presence.
        """
        repo = BindingRepo(org_id=org_id)
        out: Dict[str, List[str]] = {"vision": [], "values": [], "current": []}

        for key, query in (
            ("vision", "vision"),
            ("values", "values"),
            ("current", "current context"),
        ):
            try:
                results = repo.search_content(query, limit=3) or []
            except Exception as exc:
                # A missing or unreachable knowledge store should not break
                # the dispatcher — the goal can still be pursued without
                # context, just less aligned.
                logger.warning("Failed to load %s context for org %s: %s",
                               key, org_id, exc)
                continue

            for r in results:
                content = (r.get("content") or "").strip()
                if content:
                    out[key].append(content)

        return out

    # ----------------------------------------------------------- Pursuit

    def _pursue(
        self,
        goal: Dict[str, Any],
        instance: Optional[Dict[str, Any]],
        org_context: Dict[str, List[str]],
    ) -> tuple[str, List[Dict[str, Any]]]:
        """
        Run the agentic loop. Returns (summary_text, tool_calls).

        Builds a GuardrailContext from goal.config and runs a bounded
        Claude tool-use loop. Each tool call goes through `permit_tool`
        before execution; each Claude response runs through
        `record_usage` for cost tracking.

        If no Anthropic client is configured, returns a deterministic
        stub so the engine path is exercisable in dev and tests without
        burning API tokens.
        """
        system_prompt = self._build_system_prompt(instance, org_context)
        user_prompt = self._build_user_prompt(goal)

        if self._client is None:
            return (
                f"[no-llm] Goal pursued in offline mode: {goal['title']}",
                [],
            )

        guardrails = GuardrailContext.from_goal_config(goal.get("config") or {})
        return self._run_agentic_loop(
            goal=goal,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            guardrails=guardrails,
        )

    def _build_system_prompt(
        self,
        instance: Optional[Dict[str, Any]],
        org_context: Dict[str, List[str]],
    ) -> str:
        parts: List[str] = []

        if instance and instance.get("identity_prompt"):
            parts.append(instance["identity_prompt"])
        else:
            parts.append(
                "You are acting on behalf of an org to pursue an explicit goal. "
                "Stay aligned with the org's vision and values."
            )

        if org_context["vision"]:
            parts.append("## Vision\n" + "\n\n".join(org_context["vision"]))
        if org_context["values"]:
            parts.append("## Values\n" + "\n\n".join(org_context["values"]))
        if org_context["current"]:
            parts.append("## Current context\n" + "\n\n".join(org_context["current"]))

        parts.append(
            "When you are confident the goal is achieved, respond with a "
            "concise summary of what was accomplished. If you cannot achieve "
            "it, respond with a brief explanation of why."
        )
        return "\n\n".join(parts)

    def _build_user_prompt(self, goal: Dict[str, Any]) -> str:
        lines = [f"# Goal: {goal['title']}"]
        if goal.get("description"):
            lines.append(goal["description"])
        criteria = goal.get("target_criteria")
        if criteria:
            lines.append("## Target criteria\n" + str(criteria))
        return "\n\n".join(lines)

    def _run_agentic_loop(
        self,
        goal: Dict[str, Any],
        system_prompt: str,
        user_prompt: str,
        guardrails: GuardrailContext,
    ) -> tuple[str, List[Dict[str, Any]]]:
        """
        Bounded Claude tool-use loop with hard guardrails.

        Each iteration:
        1. begin_round() — trip on rounds / wall-clock limit.
        2. Call Claude with the available tools.
        3. record_usage() — trip on cost.
        4. If response is end_turn or text-only, exit.
        5. For each tool_use block: permit_tool() (refuses unallowed /
           write-after-write), execute via registry, record as a
           goal_event.
        6. Append tool_results and loop.
        """
        from src.tools.registry import (
            get_all_tools, get_tool, _tool_to_schema,
        )

        model = "claude-sonnet-4-6"
        if goal.get("config") and goal["config"].get("model"):
            model = goal["config"]["model"]

        # Build the tool catalog Claude will see. The goal's allowed_tools
        # gates this — Claude is only ever offered what the goal permits.
        all_tools = {t.name: t for t in get_all_tools()}
        if guardrails.allowed_tools:
            offered = [
                _tool_to_schema(all_tools[name])
                for name in guardrails.allowed_tools
                if name in all_tools
            ]
        else:
            # No allowlist → no tools (goal didn't ask for any). Loop
            # degenerates to a single Claude call.
            offered = []

        messages: List[Dict[str, Any]] = [
            {"role": "user", "content": user_prompt},
        ]
        tool_call_summaries: List[Dict[str, Any]] = []

        last_text = ""

        # Shared tenancy OrgContext for this dispatch (arch §4.1). Goal dispatch
        # resolves trivially: the goal's org, acting as a claw under the org's
        # own service authority (arch §4.2, §8). Threaded into every tool ctx so
        # tools resolve org-scoped connections from it rather than ad-hoc org_id.
        from src.services.org_context import OrgContext
        _org_id = goal.get("org_id")
        _inst = self._load_instance(_org_id) if _org_id is not None else None
        _inst_id = (_inst or {}).get("id")
        tenancy_ctx = (
            OrgContext(org_id=_org_id, instance_id=_inst_id,
                       actor_type="claw", authority="service")
            if _inst_id is not None and _org_id is not None
            else None
        )

        while True:
            guardrails.begin_round()  # may raise GuardrailTripped

            create_kwargs: Dict[str, Any] = {
                "model": model,
                "max_tokens": DEFAULT_MAX_TOKENS,
                "system": system_prompt,
                "messages": messages,
            }
            if offered:
                create_kwargs["tools"] = offered

            response = self._client.messages.create(**create_kwargs)

            usage_cost = guardrails.record_usage(
                getattr(response, "usage", None), model,
            )
            logger.debug(
                "goal=%s round=%s cost=%.6f total=%.6f",
                goal["id"], guardrails.rounds_used, usage_cost,
                guardrails.cost_used_usd,
            )

            # Capture any text emitted this round (model may interleave
            # text + tool_use blocks).
            round_text = ""
            tool_uses = []
            for block in response.content:
                btype = getattr(block, "type", None)
                if btype == "text":
                    round_text += getattr(block, "text", "") or ""
                elif btype == "tool_use":
                    tool_uses.append(block)
            if round_text:
                last_text = round_text

            stop_reason = getattr(response, "stop_reason", None)
            if stop_reason != "tool_use" or not tool_uses:
                # Conversation done.
                break

            # Echo the assistant turn back so Claude has continuity, then
            # run each tool and append tool_results in a single user turn.
            # SDK response objects don't round-trip through messages.create;
            # serialize each block to a plain dict before appending.
            assistant_content: List[Dict[str, Any]] = []
            for block in response.content:
                btype2 = getattr(block, "type", None)
                if btype2 == "tool_use":
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })
                elif btype2 == "text":
                    assistant_content.append({
                        "type": "text",
                        "text": getattr(block, "text", "") or "",
                    })
            messages.append({"role": "assistant", "content": assistant_content})

            tool_result_blocks: List[Dict[str, Any]] = []
            for use in tool_uses:
                name = use.name
                tool_input = use.input or {}
                use_id = use.id

                tool = all_tools.get(name)
                if tool is None:
                    err = f"Unknown tool: {name!r}"
                    self._record_tool_event(
                        goal["id"], name, err, {"error": "unknown_tool"},
                    )
                    tool_call_summaries.append(
                        {"name": name, "ok": False, "summary": err},
                    )
                    tool_result_blocks.append({
                        "type": "tool_result",
                        "tool_use_id": use_id,
                        "content": err,
                        "is_error": True,
                    })
                    continue

                try:
                    guardrails.permit_tool(name, is_read_only=tool.is_read_only)
                except GuardrailTripped:
                    # Re-raise — handled at the outer try in dispatch().
                    raise

                # Pass guardrails into the tool's context so tool code can
                # consult policy (e.g. slack_post checking @-mention rule).
                ctx = {
                    "goal_id": goal["id"],
                    "org_id": goal.get("org_id"),
                    "workspace_id": goal.get("workspace_id") or self._load_primary_workspace_id(
                        goal.get("org_id")
                    ),
                    "guardrails": guardrails,
                    "org_context": tenancy_ctx,
                }
                try:
                    # Draft-approval gate: FREE (read-only/internal) tools run
                    # immediately; GATED outbound/destructive tools are held as
                    # a pending_action for human approval and do NOT execute now
                    # (docs/DRAFT_APPROVAL_GATE.md). Default-deny by action type.
                    gate_result = self._draft_gate.gate_or_execute(
                        org_id=goal.get("org_id"),
                        action_type=name,
                        acting_identity=f"amebo:{goal.get('org_id')}",
                        executor=lambda _a: tool.execute(tool_input, ctx) or "",
                        target=tool_input.get("channel") or tool_input.get("to"),
                        payload=tool_input,
                        preview=f"{name} requested by claw for goal {goal.get('title')}",
                        goal_id=goal["id"],
                    )
                    if gate_result.gated:
                        pa_id = (gate_result.pending_action or {}).get("id")
                        result_text = (
                            f"[held for approval] {name} requires human approval "
                            f"before it runs. Pending action {pa_id} created."
                        )
                        is_error = False
                    else:
                        result_text = gate_result.result or ""
                        is_error = result_text.startswith("Error:")
                except Exception as exc:
                    logger.exception("Tool %s raised", name)
                    result_text = f"Tool {name} raised: {exc}"
                    is_error = True

                # Snip very long results before showing the model again,
                # but record the full thing in the event metadata.
                snippet = result_text if len(result_text) <= 4000 \
                    else result_text[:4000] + "\n[...truncated...]"

                self._record_tool_event(
                    goal["id"], name, snippet,
                    {
                        "input": tool_input,
                        "is_error": is_error,
                        "cost_so_far_usd": round(guardrails.cost_used_usd, 6),
                        "round": guardrails.rounds_used,
                    },
                )
                tool_call_summaries.append(
                    {"name": name, "ok": not is_error, "summary": snippet[:200]},
                )

                tool_result_blocks.append({
                    "type": "tool_result",
                    "tool_use_id": use_id,
                    "content": snippet,
                    "is_error": is_error,
                })

            messages.append({"role": "user", "content": tool_result_blocks})

        summary = last_text.strip() or "(model returned no final text)"
        summary += (
            f"\n\n[loop stats: rounds={guardrails.rounds_used}, "
            f"cost=${guardrails.cost_used_usd:.4f}, "
            f"tool_calls={len(tool_call_summaries)}]"
        )
        return summary, tool_call_summaries

    def _record_tool_event(
        self,
        goal_id: str,
        tool_name: str,
        result_summary: str,
        metadata: Dict[str, Any],
    ) -> None:
        """Append a tool_call event. Swallows failures — best effort."""
        try:
            self._goal_repo.append_event(
                goal_id=goal_id,
                actor_type="claw",
                action=f"tool_call:{tool_name}",
                result_summary=result_summary,
                metadata=metadata,
            )
        except Exception:
            logger.exception(
                "Failed to record tool_call event for goal %s tool %s",
                goal_id, tool_name,
            )

    # --------------------------------------------------- Credential blocking

    def _block_on_credential(
        self,
        goal: Dict[str, Any],
        exc: Exception,
    ) -> DispatchResult:
        """
        A tool raised a credential exception. Mint a connect link, record
        a typed event, and surface it through the notify channel so the
        admin can act.

        The goal stays in its current state (no transition). The scheduler
        will see the most-recent event = blocked_on_credential and skip
        this goal on subsequent ticks until something writes an
        "unblocked" event (e.g. the OAuth callback).
        """
        kind = getattr(exc, "kind", "unknown")
        org_id = goal["org_id"]

        try:
            link = mint_connect_link(
                org_id=org_id,
                kind=kind,
                requested_scopes=[],  # tool implementations declare scopes; v1 leaves empty
                reply_channel=goal.get("notify_channel"),
            )
            connect_url = _make_connect_url(link.short_code)
        except Exception:
            logger.exception("Failed to mint connect link for goal %s", goal["id"])
            connect_url = None
            link = None

        summary = (
            f"Credential needed: {kind}. "
            + (f"Connect here: {connect_url}" if connect_url else "No connect link available.")
        )

        try:
            self._goal_repo.append_event(
                goal_id=goal["id"],
                actor_type="claw",
                action=f"blocked_on_credential:{kind}",
                result_summary=summary,
                metadata={
                    "kind": kind,
                    "connect_url": connect_url,
                    "short_code": link.short_code if link else None,
                },
            )
        except Exception:
            logger.exception("Failed to record blocked_on_credential event")

        notification_sent = False
        if goal.get("notify_channel"):
            notification_sent = self._maybe_notify(goal, summary)

        return DispatchResult(
            goal_id=goal["id"],
            status="blocked_on_credential",
            summary=summary,
            notification_sent=notification_sent,
        )

    # ------------------------------------------------------------- Notify

    def _maybe_notify(self, goal: Dict[str, Any], summary: Optional[str]) -> bool:
        channel = goal.get("notify_channel")
        if not channel:
            return False

        message = (
            f"Goal completed: {goal['title']}\n\n"
            f"{summary or '(no summary)'}"
        )
        try:
            return bool(self._notify(channel, message))
        except Exception as exc:
            logger.warning("Notifier raised for goal %s: %s", goal["id"], exc)
            return False
