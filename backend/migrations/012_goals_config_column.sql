-- Migration 012: add `config` JSONB column to goals
--
-- The dispatcher reads per-goal guardrail config from this field
-- (max_tool_rounds, max_cost_usd, allowed_tools, allow_multiple_writes,
-- model selection, etc.). Without the column, the dispatcher defaults to
-- safe values, but operators have no knob to tune behavior per goal.
--
-- Additive only.

ALTER TABLE goals
    ADD COLUMN IF NOT EXISTS config JSONB DEFAULT '{}'::jsonb;

COMMENT ON COLUMN goals.config IS
    'Per-goal runtime configuration: guardrails (max_tool_rounds, max_cost_usd, '
    'wall_clock_seconds, allowed_tools, allow_multiple_writes, slack_require_mention) '
    'and model selection. Unknown keys are ignored by the dispatcher.';
