"""
Tool registry — defines tools Claude can invoke during conversations.

Pattern follows Claude Code: tools are plain objects with a standard shape,
registered in a central registry, executed by the framework. The model
decides what to search and when.

Per-instance tool permissions: each instance's config.allowed_tools controls
which tools are available. Tools not in the list are never sent to Claude.

Each tool declares:
- schema: name, description, input_schema (for Claude API)
- is_read_only: whether it only reads data (used for role-based access)
- needs_confirmation: whether it should prompt the user before executing
- execute(): the actual implementation

Adding a tool: define it below, register with @register_tool. That's it.
No changes needed anywhere else.
"""

import json
import logging
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool type
# ---------------------------------------------------------------------------

@dataclass
class Tool:
    """
    A tool that Claude can invoke.

    Modeled after Claude Code's tool objects: plain data + execute function.
    No class hierarchy, no inheritance — just a struct with a callable.

    Attributes:
        name: Unique tool identifier (matches Claude API tool_use name)
        description: What the tool does (sent to Claude)
        input_schema: JSON Schema for input validation (sent to Claude)
        execute: Callable(tool_input, context) -> str
        is_read_only: True if tool only reads data. Used for role-based filtering:
            viewers see read-only tools, coordinators get write tools too.
        needs_confirmation: True if tool should prompt user before executing.
            The agentic loop can check this and send a CONFIRM action through
            the channel contract before running the tool.
        category: Grouping for UI/documentation (e.g., "knowledge", "crm", "tasks")
    """
    name: str
    description: str
    input_schema: Dict
    execute: Callable
    is_read_only: bool = True
    needs_confirmation: bool = False
    category: str = "general"
    # Authorization class for the trust gate (arch §4.3, I10). Left None means
    # "derive from is_read_only" so existing tools get a sane default without
    # re-annotation; declare explicitly ('read'|'write'|'admin') to override
    # (e.g. an admin-class tool).
    access_class: Optional[str] = None

    @property
    def effective_access_class(self) -> str:
        if self.access_class:
            return self.access_class
        return "read" if self.is_read_only else "write"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_TOOLS: Dict[str, Tool] = {}


def register_tool(tool: Tool) -> Tool:
    """Register a tool in the global registry."""
    if tool.name in _TOOLS:
        logger.warning(f"Tool '{tool.name}' registered twice, overwriting")
    _TOOLS[tool.name] = tool
    return tool


def get_tool(name: str) -> Optional[Tool]:
    """Get a tool by name."""
    return _TOOLS.get(name)


def get_all_tools() -> List[Tool]:
    """Get all registered tools."""
    return list(_TOOLS.values())


def get_read_only_tools() -> List[Tool]:
    """Get tools that only read data (safe for viewer roles)."""
    return [t for t in _TOOLS.values() if t.is_read_only]


def get_tools_for_instance(instance: Optional[Dict] = None) -> List[Dict]:
    """
    Get tool definitions for an instance, respecting allowed_tools config.
    Returns list of tool schemas ready for the Claude API tools parameter.

    This is the same interface as before — callers don't need to change.
    """
    allowed = set(DEFAULT_TOOLS)

    if instance and instance.get('config'):
        config = instance['config']
        if isinstance(config, str):
            config = json.loads(config)
        extra = config.get('allowed_tools', [])
        allowed.update(extra)

    tools = []
    seen = set()
    for name in allowed:
        tool = _TOOLS.get(name)
        if tool and name not in seen:
            tools.append(_tool_to_schema(tool))
            seen.add(name)

    return tools


def require_org_context(org_context):
    """Fail-closed guard (I2): callers on the resolved path use this to assert an
    OrgContext is present before executing a tool. Raises MissingOrgContext."""
    from src.services.org_context import MissingOrgContext
    if org_context is None:
        raise MissingOrgContext(
            "tool execution requires a resolved OrgContext (arch §4.2, I2)"
        )
    return org_context


def trust_gate(tool: "Tool", principal) -> Optional[str]:
    """The §4.3 authorization gate (I10), in code below the model. Returns a
    refusal string if `principal` lacks the trust the tool's access_class needs,
    else None. Trust scoring is delegated to the swappable evaluator seam — this
    function never computes trust itself."""
    from src.services.trust import evaluate as trust_evaluate, required_level
    level = trust_evaluate(principal)
    need = required_level(tool.effective_access_class)
    if level < need:
        return (
            f"Refused: '{tool.name}' is a {tool.effective_access_class}-class "
            f"action requiring trust {need.name}, but the caller is {level.name}."
        )
    return None


def execute_tool(
    tool_name: str,
    tool_input: Dict,
    workspace_id: Optional[str] = None,
    org_id: Optional[int] = None,
    *,
    org_context=None,
    principal=None,
) -> str:
    """
    Execute a tool and return the result as a string.

    The framework's tool runner — called in the agentic loop when Claude returns
    a tool_use block. Backward compatible: legacy callers pass (workspace_id,
    org_id) and get today's behavior. The resolved path passes `org_context`
    (arch §4.1), which is threaded into the tool context, and optionally a
    `principal` (arch §4.3), which is checked against the trust gate BELOW the
    model — a refused tool never executes.
    """
    tool = _TOOLS.get(tool_name)
    if not tool:
        return f"Unknown tool: {tool_name}"

    # Authorization gate (code, not prompt). Only when a principal is supplied;
    # legacy/service callers without one keep prior behavior until their route
    # is wired (compat shim, removed at WP17 cutover).
    if principal is not None:
        denial = trust_gate(tool, principal)
        if denial:
            logger.info("Trust gate denied %s: %s", tool_name, denial)
            return denial

    ctx_org_id = org_context.org_id if org_context is not None else org_id
    ctx_workspace = workspace_id
    if org_context is not None and org_context.venue is not None:
        ctx_workspace = ctx_workspace or org_context.venue.workspace_ref

    context = {
        "workspace_id": ctx_workspace,
        "org_id": ctx_org_id,
        "org_context": org_context,
    }
    try:
        return tool.execute(tool_input, context)
    except Exception as e:
        logger.error(f"Tool {tool_name} failed: {e}", exc_info=True)
        return f"Error: {str(e)}"


def _tool_to_schema(tool: Tool) -> Dict:
    """Convert a Tool to Claude API tool schema format."""
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.input_schema,
    }


# ---------------------------------------------------------------------------
# Default tools list
# ---------------------------------------------------------------------------

DEFAULT_TOOLS = ["search_knowledge_base", "search_slack_history", "lookup_contact"]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _knowledge_scope(context: Dict) -> Optional[str]:
    """The acting org's abra scope from its manifest (arch §5/§7), or None. KB
    search is already org-isolated by BindingService(org_id) + the repo's
    org_filter; this adds the finer within-org scope when configured."""
    try:
        from src.tools.cli_read_tools import _conn
        c = _conn(context, "knowledge")
        return c.config.get("scope") if c is not None else None
    except Exception:
        return None


def _exec_search_kb(tool_input: Dict, context: Dict) -> str:
    """Search the knowledge base (abra content via pgvector)."""
    from src.services.binding_service import BindingService
    svc = BindingService(context.get("org_id"))
    results = svc.repo.search_content(
        query=tool_input["query"],
        scope=_knowledge_scope(context),
        limit=tool_input.get("limit", 8)
    )

    if not results:
        return "No results found in the knowledge base."

    parts = []
    seen = set()
    for r in results:
        source = r.get('source_file', 'unknown')
        if source in seen:
            continue
        seen.add(source)
        content = r.get('content', '')
        sim = r.get('similarity', 0)
        if sim and sim > 0.15:
            if len(content) > 1000:
                content = content[:1000] + "..."
            parts.append(f"[{source}] (relevance: {sim:.0%})\n{content}")

    return "\n\n---\n".join(parts) if parts else "No sufficiently relevant results found."


def _exec_search_slack(tool_input: Dict, context: Dict) -> str:
    """Search Slack message history via pgvector."""
    from src.services.query_service import QueryService
    qs = QueryService(context["workspace_id"])
    results = qs.semantic_search(
        query=tool_input["query"],
        n_results=tool_input.get("limit", 10),
        channel_filter=tool_input.get("channel"),
        days_back=tool_input.get("days_back")
    )

    if not results:
        return "No relevant Slack messages found."

    parts = []
    for msg in results:
        text = msg.get('text', '')
        if len(text.strip()) < 10:
            continue
        meta = msg.get('metadata', {})
        user = meta.get('user_name', 'unknown')
        channel = meta.get('channel_name', 'unknown')
        ts = meta.get('timestamp', '')
        parts.append(f"[#{channel}] {user} ({ts}): {text[:500]}")

    return "\n\n".join(parts[:10]) if parts else "No substantive messages found."


def _exec_lookup_contact(tool_input: Dict, context: Dict) -> str:
    """Look up a name via binding service (abra)."""
    from src.services.binding_service import BindingService
    svc = BindingService(context.get("org_id"))
    result = svc.about(tool_input["name"], scope=_knowledge_scope(context))

    if not result.get('bindings') and not result.get('content_refs'):
        return f"No information found for '{tool_input['name']}'."

    parts = [f"## {result['name']}"]
    if result.get('is_hot'):
        parts.append("[PRIORITY / HOT TAG]")

    for rel, bindings in result.get('by_relationship', {}).items():
        parts.append(f"\n{rel}:")
        for b in bindings[:5]:
            qual = f" ({b['qualifier']})" if b.get('qualifier') else ""
            parts.append(f"  - {b['target_ref']}{qual}")

    for cr in result.get('content_refs', [])[:3]:
        parts.append(f"\n[Content: {cr.get('qualifier', 'note')}]")
        parts.append(cr.get('content_preview', '')[:500])

    return "\n".join(parts)


def _exec_cli_tool(command: str, args: str = "", timeout: int = 10) -> str:
    """Run a CLI tool as subprocess with timeout. Shared by abra, odoo, taiga."""
    cmd = [command]
    if args:
        cmd.extend(args.split())

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        output = result.stdout.strip()
        if result.returncode != 0 and result.stderr:
            output += f"\n[stderr: {result.stderr.strip()[:200]}]"
        return output if output else "(no output)"
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s"
    except FileNotFoundError:
        return f"Tool '{command}' not found in PATH"


def _exec_abra(tool_input: Dict, context: Dict) -> str:
    cmd = tool_input["command"]
    args = tool_input.get("args", "")
    return _exec_cli_tool("abra", f"{cmd} {args}".strip())


def _exec_odoo_cli(tool_input: Dict, context: Dict) -> str:
    cmd = tool_input["command"]
    args = tool_input.get("args", "")
    return _exec_cli_tool("odoo-cli", f"{cmd} {args}".strip())


def _exec_mcp_taiga(tool_input: Dict, context: Dict) -> str:
    cmd = tool_input["command"]
    args = tool_input.get("args", "")
    return _exec_cli_tool("mcp-taiga", f"{cmd} {args}".strip())


# ---------------------------------------------------------------------------
# Register all tools
# ---------------------------------------------------------------------------

register_tool(Tool(
    name="search_knowledge_base",
    description=(
        "Semantic search over the team's knowledge base (abra): project docs, "
        "plans, meeting notes, reference docs, ideas, outreach materials. Use "
        "when the user asks about projects, plans, strategy, or team activities. "
        "For everything known about ONE named person/project, prefer "
        "lookup_contact or the 'abra' tool's about. Returns the most relevant "
        "documents."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query — describe what you're looking for"
            },
            "limit": {
                "type": "integer",
                "description": "Max results to return (default 8)",
                "default": 8
            }
        },
        "required": ["query"]
    },
    execute=_exec_search_kb,
    is_read_only=True,
    category="knowledge",
))

register_tool(Tool(
    name="search_slack_history",
    description=(
        "Search Slack message history for the workspace. Use this when the user "
        "asks about conversations, what people said, decisions made in chat, "
        "or recent activity. Returns messages ranked by relevance."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query"
            },
            "channel": {
                "type": "string",
                "description": "Optional: filter to a specific channel name"
            },
            "days_back": {
                "type": "integer",
                "description": "Optional: only search messages from the last N days"
            },
            "limit": {
                "type": "integer",
                "description": "Max results (default 10)",
                "default": 10
            }
        },
        "required": ["query"]
    },
    execute=_exec_search_slack,
    is_read_only=True,
    category="knowledge",
))

register_tool(Tool(
    name="lookup_contact",
    description=(
        "Look up everything known about a person, project, or organization. "
        "Returns relationships, roles, meeting notes, and context from the "
        "knowledge base. Use when the user mentions a name or asks 'who is X'."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name of person, project, or organization"
            }
        },
        "required": ["name"]
    },
    execute=_exec_lookup_contact,
    is_read_only=True,
    category="knowledge",
))

register_tool(Tool(
    name="abra",
    description=(
        "Query the abra knowledge base CLI. Supports: search <query>, "
        "about <name>, who <topic>, related <name>, hot (priority items), "
        "refs (reference docs). Use for structured lookups (who/related/hot/"
        "refs) that plain document search does not cover."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "abra subcommand (search, about, who, related, hot, refs)"
            },
            "args": {
                "type": "string",
                "description": "Arguments for the command"
            }
        },
        "required": ["command"]
    },
    execute=_exec_abra,
    is_read_only=True,
    category="knowledge",
))

register_tool(Tool(
    name="odoo_cli",
    description=(
        "General CRM (Odoo) CLI access (can write, so gated). Search contacts, "
        "check follow-ups, manage tags. Commands: search contacts <query>, "
        "search leads <query>, show contact <id>, list tags. For a plain read "
        "prefer odoo_search."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "odoo-cli command to run"
            },
            "args": {
                "type": "string",
                "description": "Arguments for the command"
            }
        },
        "required": ["command"]
    },
    execute=_exec_odoo_cli,
    is_read_only=False,          # CRM has write operations
    needs_confirmation=True,      # Confirm before CRM changes
    category="crm",
))

# ---------------------------------------------------------------------------
# Additional general-purpose tools (no per-org credentials required)
# ---------------------------------------------------------------------------

from src.tools.http_fetch import http_fetch, HTTP_FETCH_SCHEMA
from src.tools.goal_introspection import (
    list_goals, LIST_GOALS_SCHEMA,
    get_goal_events, GET_GOAL_EVENTS_SCHEMA,
)
from src.tools.hot_tags import list_hot_tags, LIST_HOT_TAGS_SCHEMA


register_tool(Tool(
    name="http_fetch",
    description=(
        "Fetch the text content of a public http/https URL. Use this when the "
        "user references a webpage or you need to read documentation on the open "
        "web. Internal/private addresses are refused. Non-text content (images, "
        "binaries) is refused. Response is truncated to 256 KB by default."
    ),
    input_schema=HTTP_FETCH_SCHEMA,
    execute=http_fetch,
    is_read_only=True,
    category="web",
))


register_tool(Tool(
    name="list_goals",
    description=(
        "List the current org's amebo claws. NOTE: a 'goal' here means an "
        "amebo background pursuit (a claw) in amebo's own goals table, NOT a "
        "project goal narrative in abra or the projects repo. Use when asked "
        "what claws/pursuits are running. Optional status filter: pending, "
        "active, completed, failed, paused."
    ),
    input_schema=LIST_GOALS_SCHEMA,
    execute=list_goals,
    is_read_only=True,
    category="goals",
))


register_tool(Tool(
    name="get_goal_events",
    description=(
        "Get the full audit trail (every state change and tool call) for one "
        "amebo claw. Here 'goal' = an amebo claw/pursuit (amebo's goal_events "
        "table), not an abra goal narrative. Use for 'what has the claw done "
        "on X' or 'show the history of claw/goal Y'."
    ),
    input_schema=GET_GOAL_EVENTS_SCHEMA,
    execute=get_goal_events,
    is_read_only=True,
    category="goals",
))


register_tool(Tool(
    name="list_hot_tags",
    description=(
        "List the org's hot tags — priority items, current focus areas, "
        "and topics flagged as important. Use to anchor your responses on "
        "what currently matters to this team."
    ),
    input_schema=LIST_HOT_TAGS_SCHEMA,
    execute=list_hot_tags,
    is_read_only=True,
    category="knowledge",
))


register_tool(Tool(
    name="mcp_taiga",
    description=(
        "General Taiga CLI access (can write, so gated). List tasks, check "
        "status, find assigned work. For a plain read prefer taiga_list; to "
        "create a task use taiga_create_task (which routes through approval). "
        "Use this for other Taiga commands."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "mcp-taiga command to run"
            },
            "args": {
                "type": "string",
                "description": "Arguments for the command"
            }
        },
        "required": ["command"]
    },
    execute=_exec_mcp_taiga,
    is_read_only=False,          # Task management has write operations
    needs_confirmation=True,      # Confirm before task changes
    category="tasks",
))


# ---------------------------------------------------------------------------
# Claw loop tools — MAIN.md updater + Slack post
# ---------------------------------------------------------------------------

from src.tools.main_md_tools import (
    list_projects_impl,
    LIST_PROJECTS_SCHEMA,
    read_main_md_impl,
    READ_MAIN_MD_SCHEMA,
    edit_main_md_impl,
    EDIT_MAIN_MD_SCHEMA,
    create_main_md_impl,
    CREATE_MAIN_MD_SCHEMA,
)
from src.tools.slack_tools import slack_post_impl, SLACK_POST_SCHEMA


register_tool(Tool(
    name="list_projects",
    description=(
        "List the team's active projects (directory names under "
        "/opt/shared/projects/Active/). Use this first to know which "
        "project slugs are valid before reading or editing a MAIN.md."
    ),
    input_schema=LIST_PROJECTS_SCHEMA,
    execute=list_projects_impl,
    is_read_only=True,
    category="projects",
))


register_tool(Tool(
    name="read_main_md",
    description=(
        "Read a project's MAIN.md file. Each active project has a "
        "MAIN.md with team lead, slack channel, repos, demo links, and "
        "background. Pass the project_slug exactly as returned by "
        "list_projects."
    ),
    input_schema=READ_MAIN_MD_SCHEMA,
    execute=read_main_md_impl,
    is_read_only=True,
    category="projects",
))


register_tool(Tool(
    name="edit_main_md",
    description=(
        "Edit a project's MAIN.md via exact-substring replacement. "
        "old_string must be present in the file and unique. This writes the "
        "file directly (ungated, not a draft); the change lands on disk "
        "uncommitted, and a human reviews via git diff before committing. Use "
        "this ONLY when you have a clearly sourced update (e.g. a recent Slack "
        "decision) and have already read the file."
    ),
    input_schema=EDIT_MAIN_MD_SCHEMA,
    execute=edit_main_md_impl,
    is_read_only=False,
    category="projects",
))


register_tool(Tool(
    name="create_main_md",
    description=(
        "Create a NEW MAIN.md for a project that does not have one yet. "
        "Refuses to overwrite an existing MAIN.md (use edit_main_md for those). "
        "Creates the project directory under /opt/shared/projects/Active/ if "
        "needed. ALWAYS read an existing project's MAIN.md first with "
        "read_main_md so the new one follows the exact pattern. Use the team's "
        "own words and do not invent facts — ask the person for anything you "
        "don't have. The file lands on disk uncommitted; a human reviews via "
        "git diff before committing."
    ),
    input_schema=CREATE_MAIN_MD_SCHEMA,
    execute=create_main_md_impl,
    is_read_only=False,
    category="projects",
))


register_tool(Tool(
    name="slack_post",
    description=(
        "Post a message to Slack directly (ungated). To actually NOTIFY a "
        "person, you MUST pass mention_user_id with their Slack user id "
        "(e.g. UHUUD9ERZ); a post without an @-mention generates no "
        "notification (it is just channel noise). Use thread_ts to reply "
        "inside an existing thread. In gated instances use slack_post_gated, "
        "which requires human approval before sending."
    ),
    input_schema=SLACK_POST_SCHEMA,
    execute=slack_post_impl,
    is_read_only=False,
    category="comms",
))


# ---------------------------------------------------------------------------
# Amebo tool layer — "eyes" (read, ungated) and "hands" (outbound, gated).
#
# READ tools are side-effect-free CLI lookups, classified FREE in
# gated_actions and so always exposed when allowed. GATED actuators route
# every outbound action through the EXISTING DraftApprovalService gate (they
# create a pending_action and return it instead of performing the side
# effect). All are behind per-instance allowed_tools, like every other tool.
# See docs/TOOL_LAYER.md.
# ---------------------------------------------------------------------------

from src.tools.cli_read_tools import (
    odoo_search_impl, ODOO_SEARCH_SCHEMA,
    crm_read_latest_email_impl, CRM_READ_LATEST_EMAIL_SCHEMA,
    crm_recent_activity_impl, CRM_RECENT_ACTIVITY_SCHEMA,
    crm_list_leads_impl, CRM_LIST_LEADS_SCHEMA,
    crm_list_contacts_impl, CRM_LIST_CONTACTS_SCHEMA,
    load_skill_impl, LOAD_SKILL_SCHEMA,
    abra_search_impl, ABRA_SEARCH_SCHEMA,
    taiga_list_impl, TAIGA_LIST_SCHEMA,
)
from src.tools.gated_actuators import (
    taiga_create_task_impl, TAIGA_CREATE_TASK_SCHEMA,
    taiga_update_task_impl, TAIGA_UPDATE_TASK_SCHEMA,
    taiga_add_comment_impl, TAIGA_ADD_COMMENT_SCHEMA,
    taiga_close_task_impl, TAIGA_CLOSE_TASK_SCHEMA,
    slack_post_impl as slack_post_gated_impl, SLACK_POST_SCHEMA as SLACK_POST_GATED_SCHEMA,
)


# --- Read tools (ungated) --------------------------------------------------

register_tool(Tool(
    name="odoo_search",
    description=(
        "Search the CRM (Odoo) for contacts or leads matching a query. "
        "Read only — never writes. Use when asked who/what contacts exist "
        "for a person, company, or email fragment."
    ),
    input_schema=ODOO_SEARCH_SCHEMA,
    execute=odoo_search_impl,
    is_read_only=True,
    category="crm",
))

register_tool(Tool(
    name="crm_read_latest_email",
    description=(
        "Read the latest forwarded email logged in the CRM for a given sender "
        "(email address or contact). 'Chatter' here means the Odoo CRM message "
        "log on a contact (via odoo-cli comms), not Slack chatter. Read only. "
        "Use to see someone's most recent message before drafting a reply."
    ),
    input_schema=CRM_READ_LATEST_EMAIL_SCHEMA,
    execute=crm_read_latest_email_impl,
    is_read_only=True,
    category="crm",
))

register_tool(Tool(
    name="crm_recent_activity",
    description=(
        "Show the most recent chatter (emails/notes) across the WHOLE CRM, "
        "newest first — NOT scoped to one contact. Read only. Use this for "
        "'what's been happening in the CRM lately', 'recent chatter', or a "
        "general activity briefing. Optional 'limit' (default 15)."
    ),
    input_schema=CRM_RECENT_ACTIVITY_SCHEMA,
    execute=crm_recent_activity_impl,
    is_read_only=True,
    category="crm",
))

register_tool(Tool(
    name="crm_list_leads",
    description=(
        "List CRM leads/opportunities (the pipeline), most-recently-updated "
        "first, with stage, owner, and expected revenue. Optional 'stage' name "
        "filter. Read only. Use for 'where does the pipeline stand', 'what's in "
        "the proposal stage', etc."
    ),
    input_schema=CRM_LIST_LEADS_SCHEMA,
    execute=crm_list_leads_impl,
    is_read_only=True,
    category="crm",
))

register_tool(Tool(
    name="crm_list_contacts",
    description=(
        "Browse/list CRM contacts. Optional 'query' (name/email/company/"
        "catcode); omit it to list recent contacts. Read only. Use for 'list "
        "our contacts', browsing by company, etc. — broader than odoo_search."
    ),
    input_schema=CRM_LIST_CONTACTS_SCHEMA,
    execute=crm_list_contacts_impl,
    is_read_only=True,
    category="crm",
))

register_tool(Tool(
    name="load_skill",
    description=(
        "Load the full instructions for a named skill. Your system prompt lists "
        "the available skills (name: description); call this to pull a skill's "
        "detailed steps before answering. You may load more than one. Read only."
    ),
    input_schema=LOAD_SKILL_SCHEMA,
    execute=load_skill_impl,
    is_read_only=True,
    category="skills",
))

register_tool(Tool(
    name="abra_search",
    description=(
        "Search the team knowledge base (abra), read only: mode='search' for "
        "full-text, mode='about' for everything known about a name. Thin "
        "wrapper; for who/related/hot/refs use the 'abra' tool."
    ),
    input_schema=ABRA_SEARCH_SCHEMA,
    execute=abra_search_impl,
    is_read_only=True,
    category="knowledge",
))

register_tool(Tool(
    name="taiga_list",
    description=(
        "List tasks in a Taiga project. A project slug/name is REQUIRED "
        "(use mcp_taiga 'projects' to find slugs). Read only. Use to check "
        "current tasks/status before drafting a new task."
    ),
    input_schema=TAIGA_LIST_SCHEMA,
    execute=taiga_list_impl,
    is_read_only=True,
    category="tasks",
))


# --- Gated actuators (outbound — routed through draft-approval gate) -------

register_tool(Tool(
    name="taiga_create_task",
    description=(
        "Create a Taiga task. OUTBOUND: this does not create the task "
        "directly — it drafts a pending action that a human must approve "
        "before the task is created. Returns the pending action id."
    ),
    input_schema=TAIGA_CREATE_TASK_SCHEMA,
    execute=taiga_create_task_impl,
    is_read_only=False,
    needs_confirmation=True,
    category="tasks",
))

register_tool(Tool(
    name="taiga_update_task",
    description=(
        "Update a Taiga story (status, assignee, due date, description). "
        "OUTBOUND: drafts a pending action a human must approve before it applies."
    ),
    input_schema=TAIGA_UPDATE_TASK_SCHEMA,
    execute=taiga_update_task_impl,
    is_read_only=False,
    needs_confirmation=True,
    category="tasks",
))

register_tool(Tool(
    name="taiga_add_comment",
    description=(
        "Add a comment to a Taiga story. OUTBOUND: drafts a pending action a "
        "human must approve before the comment is posted."
    ),
    input_schema=TAIGA_ADD_COMMENT_SCHEMA,
    execute=taiga_add_comment_impl,
    is_read_only=False,
    needs_confirmation=True,
    category="tasks",
))

register_tool(Tool(
    name="taiga_close_task",
    description=(
        "Close a Taiga story (move it to a done status). OUTBOUND: drafts a "
        "pending action a human must approve before it applies."
    ),
    input_schema=TAIGA_CLOSE_TASK_SCHEMA,
    execute=taiga_close_task_impl,
    is_read_only=False,
    needs_confirmation=True,
    category="tasks",
))

register_tool(Tool(
    name="slack_post_gated",
    description=(
        "Post a message to Slack THROUGH THE APPROVAL GATE. OUTBOUND: it does "
        "not post directly — it drafts a pending action that a human must "
        "approve before the message is sent. Pass mention_user_id to notify a "
        "person, thread_ts to reply in a thread. Returns the pending action id."
    ),
    input_schema=SLACK_POST_GATED_SCHEMA,
    execute=slack_post_gated_impl,
    is_read_only=False,
    needs_confirmation=True,
    category="comms",
))
