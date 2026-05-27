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


def execute_tool(
    tool_name: str,
    tool_input: Dict,
    workspace_id: str,
    org_id: Optional[int] = None
) -> str:
    """
    Execute a tool and return the result as a string.

    This is the framework's tool runner — called in the agentic loop
    when Claude returns a tool_use block. Same interface as before.
    """
    tool = _TOOLS.get(tool_name)
    if not tool:
        return f"Unknown tool: {tool_name}"

    context = {"workspace_id": workspace_id, "org_id": org_id}
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

def _exec_search_kb(tool_input: Dict, context: Dict) -> str:
    """Search the knowledge base (abra content via pgvector)."""
    from src.services.binding_service import BindingService
    svc = BindingService(context.get("org_id"))
    results = svc.repo.search_content(
        query=tool_input["query"],
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
    result = svc.about(tool_input["name"])

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
        "Search the team's knowledge base — project docs, plans, meeting notes, "
        "reference docs, ideas, outreach materials. Use this when the user asks "
        "about projects, plans, strategy, team activities, or anything that might "
        "be documented. Returns the most relevant documents."
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
        "refs (reference docs). Use for structured knowledge lookups."
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
        "Access the CRM (Odoo). Search contacts, check follow-ups, manage tags. "
        "Commands: search contacts <query>, search leads <query>, "
        "show contact <id>, list tags."
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
        "List goals for the current org. Use when the user asks about active "
        "goals, what the team is working on, or to enumerate pursuits. "
        "Optional status filter: pending, active, completed, failed, paused."
    ),
    input_schema=LIST_GOALS_SCHEMA,
    execute=list_goals,
    is_read_only=True,
    category="goals",
))


register_tool(Tool(
    name="get_goal_events",
    description=(
        "Get the full audit trail for a specific goal: every state change "
        "and tool call recorded. Use when the user asks 'what has the claw "
        "done on X' or 'show me the history of goal Y'."
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
        "Access Taiga project management. List tasks, check status, "
        "find assigned work. Use when asked about task status, sprints, "
        "or project management."
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
