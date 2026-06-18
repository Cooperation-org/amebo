"""
Hard guardrails for the claw loop.

A cheaper model in an agentic loop will misbehave. The dispatcher must
refuse anything that would let it run away: too many rounds, too much
spend, write tools when only reads are allowed, write tools called a
second time when the goal said "stop after one edit", goals dragging on
past a deadline.

This is enforced — not aspirational. Every tool call goes through
`GuardrailContext.permit_tool()` before execution, and every Claude
response increments cost. On the first trip, the loop stops and the
goal is failed with the reason recorded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Set


# Default per-token prices for Anthropic models. Used to estimate cost
# from the `usage` block on a Claude response. Tune as Anthropic publishes
# updated rates; these are conservative ballparks. Per-million-tokens USD.
DEFAULT_PRICING_USD_PER_MTOK: Dict[str, Dict[str, float]] = {
    # Claude Sonnet 4 family
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    # Claude Opus 4 family
    "claude-opus-4-8":   {"input": 15.00, "output": 75.00},
    # Claude Haiku 4 family (lightweight default for the claw)
    "claude-haiku-4-5-20251001":{"input": 1.00, "output": 5.00},
    # Fallback used when the model is unknown
    "__default__":              {"input": 3.00, "output": 15.00},
}


class GuardrailTripped(RuntimeError):
    """
    Raised when a guardrail refuses an action. Carries which guardrail
    fired and a human-readable reason, so the dispatcher can write a
    typed event and fail the goal cleanly.
    """

    def __init__(self, which: str, reason: str, **metadata: Any):
        super().__init__(f"guardrail {which}: {reason}")
        self.which = which
        self.reason = reason
        self.metadata = metadata


@dataclass
class GuardrailContext:
    """
    State container for one dispatch. Constructed from the goal's
    `config` field plus sensible defaults.

    Field names map directly to goal.config keys where applicable so
    operators can tune behavior without changing code.
    """

    # ---- Limits (configurable per goal) -------------------------------
    max_tool_rounds:    int   = 5
    max_cost_usd:       float = 0.50
    wall_clock_seconds: int   = 5 * 60
    allowed_tools:      Set[str] = field(default_factory=set)
    write_tools:        Set[str] = field(default_factory=set)  # names that count as "write"
    allow_multiple_writes: bool = False
    slack_require_mention: bool = True

    # ---- Runtime state (managed by the dispatcher) --------------------
    rounds_used:        int   = 0
    cost_used_usd:      float = 0.0
    write_tools_used:   int   = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_tool_name:     Optional[str] = None

    # ---------------------------------------------------------------- API

    @classmethod
    def from_goal_config(cls, config: Optional[Dict[str, Any]]) -> "GuardrailContext":
        """
        Build a context from a goal's config blob. Unknown keys are
        ignored — operators can stash extra metadata in config without
        breaking the guardrail loader.
        """
        config = config or {}

        allowed_tools = set(config.get("allowed_tools") or [])
        # The default write-tool set must be a subset of allowed_tools; if
        # the goal explicitly lists writes, use that; otherwise fall back
        # to a known list of write-capable tools.
        write_tools = set(config.get("write_tools") or [
            "edit_main_md", "slack_post",
        ])
        write_tools = write_tools & allowed_tools  # never enforce writes that aren't allowed

        return cls(
            max_tool_rounds=int(config.get("max_tool_rounds", 5)),
            max_cost_usd=float(config.get("max_cost_usd", 0.50)),
            wall_clock_seconds=int(config.get("wall_clock_seconds", 300)),
            allowed_tools=allowed_tools,
            write_tools=write_tools,
            allow_multiple_writes=bool(config.get("allow_multiple_writes", False)),
            slack_require_mention=bool(config.get("slack_require_mention", True)),
        )

    # ----------------------------------------------------- Per-round hooks

    def begin_round(self) -> None:
        """Call before each Claude turn. Trips if we've hit the round cap."""
        if self.rounds_used >= self.max_tool_rounds:
            raise GuardrailTripped(
                "max_tool_rounds",
                f"already used {self.rounds_used} of {self.max_tool_rounds} rounds.",
                rounds_used=self.rounds_used,
                max_tool_rounds=self.max_tool_rounds,
            )
        if self._wall_clock_exceeded():
            raise GuardrailTripped(
                "wall_clock",
                f"goal ran past {self.wall_clock_seconds}s deadline.",
                wall_clock_seconds=self.wall_clock_seconds,
            )
        self.rounds_used += 1

    def record_usage(self, usage: Optional[Dict[str, Any]], model: str) -> float:
        """
        Add the cost of one Claude response to the running total. Returns
        the incremental cost (so callers can log it). Trips if budget is
        exceeded.

        usage is the .usage attribute from the Anthropic response;
        supports input_tokens / output_tokens / cache_*_tokens fields.
        """
        if not usage:
            return 0.0

        rates = DEFAULT_PRICING_USD_PER_MTOK.get(
            model, DEFAULT_PRICING_USD_PER_MTOK["__default__"],
        )
        in_tok  = int(getattr(usage, "input_tokens", 0) or 0)
        out_tok = int(getattr(usage, "output_tokens", 0) or 0)
        # Cache reads / cache creation rates approximated as input rate.
        cache_create = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        cache_read   = int(getattr(usage, "cache_read_input_tokens", 0) or 0)

        cost = (
            (in_tok + cache_create + cache_read) * rates["input"]
            + out_tok * rates["output"]
        ) / 1_000_000

        self.cost_used_usd += cost
        if self.cost_used_usd > self.max_cost_usd:
            raise GuardrailTripped(
                "max_cost_usd",
                f"goal cost ${self.cost_used_usd:.4f} exceeds ${self.max_cost_usd:.2f}.",
                cost_used_usd=self.cost_used_usd,
                max_cost_usd=self.max_cost_usd,
            )
        return cost

    # --------------------------------------------------- Per-tool-call hooks

    def permit_tool(self, tool_name: str, is_read_only: bool) -> None:
        """
        Authorize one tool call. Raises GuardrailTripped if the call is
        refused. Updates internal state on success (counter, etc.).

        is_read_only comes from the tool's Tool.is_read_only attribute —
        not from the goal config — so the registry's ground truth wins.
        """
        if not tool_name:
            raise GuardrailTripped(
                "unknown_tool", "empty tool name.", tool_name=tool_name,
            )

        if self.allowed_tools and tool_name not in self.allowed_tools:
            raise GuardrailTripped(
                "not_allowed",
                f"tool {tool_name!r} is not in this goal's allowed_tools.",
                tool_name=tool_name,
                allowed=sorted(self.allowed_tools),
            )

        if self._wall_clock_exceeded():
            raise GuardrailTripped(
                "wall_clock",
                f"deadline {self.wall_clock_seconds}s passed mid-tool-call.",
                wall_clock_seconds=self.wall_clock_seconds,
            )

        # Write-tool budget — applies to any tool the goal calls "write" OR
        # any tool the registry says is not read-only.
        is_write = (not is_read_only) or (tool_name in self.write_tools)
        if is_write:
            if self.write_tools_used >= 1 and not self.allow_multiple_writes:
                raise GuardrailTripped(
                    "write_once",
                    f"write tool {tool_name!r} called after one write already "
                    "succeeded; goal does not allow multiple writes.",
                    tool_name=tool_name,
                    write_tools_used=self.write_tools_used,
                )
            self.write_tools_used += 1

        self.last_tool_name = tool_name

    # ------------------------------------------------------------ Helpers

    def _wall_clock_exceeded(self) -> bool:
        elapsed = (datetime.now(timezone.utc) - self.started_at).total_seconds()
        return elapsed > self.wall_clock_seconds

    def summary(self) -> Dict[str, Any]:
        return {
            "rounds_used": self.rounds_used,
            "cost_used_usd": round(self.cost_used_usd, 6),
            "write_tools_used": self.write_tools_used,
            "elapsed_seconds": (
                datetime.now(timezone.utc) - self.started_at
            ).total_seconds(),
            "limits": {
                "max_tool_rounds": self.max_tool_rounds,
                "max_cost_usd": self.max_cost_usd,
                "wall_clock_seconds": self.wall_clock_seconds,
                "allow_multiple_writes": self.allow_multiple_writes,
            },
        }
