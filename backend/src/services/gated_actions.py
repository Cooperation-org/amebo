"""
Gated-action registry — the policy that decides which action types a claw may
perform unsupervised and which require a human to approve first.

The strategic rule (see docs/DRAFT_APPROVAL_GATE.md):

    A background claw must NEVER take an irreversible OUTBOUND or DESTRUCTIVE
    action without a human approving first. Read-only and internal actions are
    not gated.

This module is intentionally small and declarative. It is the single source of
truth for the classification; both the gate function and the API consult it.

Design choices:

- DEFAULT-DENY for outbound. `requires_approval` returns True for anything not
  explicitly listed as FREE. If a new action type appears that nobody has
  classified, it is gated — the conservative, safe default. You cannot
  accidentally let an unreviewed action type slip out the door.

- Action types line up with the tool names in src/tools/registry.py. A tool's
  `is_read_only` flag already encodes read-vs-write, but read-only is NOT the
  same as "safe to do unsupervised": some non-read-only actions are internal
  and reversible (e.g. editing an uncommitted MAIN.md on disk, which a human
  reviews via git diff before committing), while a read-only action is always
  free. So the gate keys off this explicit registry, not off is_read_only
  alone, and stays conservative where they disagree.
"""

from __future__ import annotations

from typing import Set


# FREE: read-only or internal/reversible actions. Safe for a claw to perform
# unsupervised. Anything here is explicitly vouched for as NOT outbound and NOT
# destructive-to-the-outside-world.
#
# Note edit_main_md is FREE: it writes only to a local working tree and the
# change is uncommitted until a human reviews it via git diff (see the tool's
# own description in registry.py). It is internal and reversible, so it does
# not need the approval gate.
FREE_ACTIONS: Set[str] = {
    # Knowledge / read-only lookups
    "search_knowledge_base",
    "search_slack_history",
    "lookup_contact",
    "abra",
    "http_fetch",
    "web_search",     # external search query only; no org data leaves
    "web_research",   # same — You.com research with citations
    "list_goals",
    "get_goal_events",
    "list_hot_tags",
    "list_projects",
    "read_main_md",
    "read_org_file",     # reads a file from the org's context repo (read-only)
    # Read tools — Amebo's "eyes" (cli_read_tools.py). Side-effect-free CLI
    # lookups; safe to run unsupervised.
    "odoo_search",
    "crm_read_latest_email",
    "crm_recent_activity",
    "crm_list_leads",
    "crm_list_contacts",
    "abra_search",
    "taiga_list",
    # Internal, reversible write (lands uncommitted; human reviews git diff)
    "edit_main_md",
    # ask_user pauses the goal (waiting_user) and puts the question on the
    # human's needs-input page — it IS the act of deferring to a human, so
    # gating it behind human approval defeats its purpose (seen live
    # 2026-07-06: claw's question became an approval draft nobody saw and
    # the goal completed unasked).
    "ask_user",
}


# GATED: irreversible outbound or destructive actions. A claw must create a
# pending_action and wait for a human to approve before any of these run.
# Listed explicitly for documentation/auditing; classification still
# default-denies, so an unlisted action type is also gated.
GATED_ACTIONS: Set[str] = {
    "slack_post",        # sends a message to Slack (outbound)
    "slack_post_gated",  # actuator (gated_actuators.py) — Slack post via the gate
    "taiga_create_task", # actuator (gated_actuators.py) — creates a Taiga task (outbound)
    "taiga_update_task", # actuator — updates a Taiga story (status/assignee/due)
    "taiga_add_comment", # actuator — comments on a Taiga story
    "taiga_close_task",  # actuator — moves a Taiga story to a done status
    "crm_schedule",      # actuator — set a next step/activity on a CRM contact
    "crm_tag_contact",   # actuator — tag a CRM contact
    "crm_log_contacted", # actuator — log last-contacted on a CRM contact
    "send_email",        # sends email (outbound)
    "odoo_cli",          # writes to the CRM (destructive/outbound side effects)
    "mcp_taiga",         # writes to Taiga task management (destructive/outbound)
    "open_pr",           # opens a pull request (outbound)
    "merge_pr",          # merges a pull request (irreversible)
}


def is_free(action_type: str) -> bool:
    """True iff the action type is explicitly classified as read-only/internal
    and therefore safe to run unsupervised."""
    return action_type in FREE_ACTIONS


def is_gated(action_type: str) -> bool:
    """True iff the action requires human approval before execution.

    Default-deny: anything not explicitly FREE is gated. This is the
    conservative posture — an unclassified or brand-new action type is gated
    until someone vouches for it by adding it to FREE_ACTIONS.
    """
    return action_type not in FREE_ACTIONS


def requires_approval(action_type: str) -> bool:
    """Public alias matching the gate's vocabulary. See is_gated."""
    return is_gated(action_type)
