"""
Tool registry — defines tools Claude can invoke during conversations.

Pattern follows Claude Code: tools are defined as schemas, executed by the
framework, results fed back into the conversation. The model decides what
to search and when, rather than the framework doing pre-retrieval.

Per-instance tool permissions: each instance's config.allowed_tools controls
which tools are available. Tools not in the list are never sent to Claude.
"""

import json
import logging
import subprocess
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# --- Tool definitions (Claude API tool schema format) ---

TOOL_DEFINITIONS = {
    "search_knowledge_base": {
        "name": "search_knowledge_base",
        "description": (
            "Search the team's knowledge base — project docs, plans, meeting notes, "
            "reference docs, ideas, outreach materials. Use this when the user asks "
            "about projects, plans, strategy, team activities, or anything that might "
            "be documented. Returns the most relevant documents."
        ),
        "input_schema": {
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
        }
    },

    "search_slack_history": {
        "name": "search_slack_history",
        "description": (
            "Search Slack message history for the workspace. Use this when the user "
            "asks about conversations, what people said, decisions made in chat, "
            "or recent activity. Returns messages ranked by relevance."
        ),
        "input_schema": {
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
        }
    },

    "lookup_contact": {
        "name": "lookup_contact",
        "description": (
            "Look up everything known about a person, project, or organization. "
            "Returns relationships, roles, meeting notes, and context from the "
            "knowledge base. Use when the user mentions a name or asks 'who is X'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of person, project, or organization"
                }
            },
            "required": ["name"]
        }
    },

    "abra": {
        "name": "abra",
        "description": (
            "Query the abra knowledge base CLI. Supports: search <query>, "
            "about <name>, who <topic>, related <name>, hot (priority items), "
            "refs (reference docs). Use for structured knowledge lookups."
        ),
        "input_schema": {
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
        }
    },

    "odoo_cli": {
        "name": "odoo_cli",
        "description": (
            "Access the CRM (Odoo). Search contacts, check follow-ups, manage tags. "
            "Commands: search contacts <query>, search leads <query>, "
            "show contact <id>, list tags."
        ),
        "input_schema": {
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
        }
    },

    "mcp_taiga": {
        "name": "mcp_taiga",
        "description": (
            "Access Taiga project management. List tasks, check status, "
            "find assigned work. Use when asked about task status, sprints, "
            "or project management."
        ),
        "input_schema": {
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
        }
    }
}

# Default tools available to all instances
DEFAULT_TOOLS = ["search_knowledge_base", "search_slack_history", "lookup_contact"]


def get_tools_for_instance(instance: Optional[Dict] = None) -> List[Dict]:
    """
    Get tool definitions for an instance, respecting allowed_tools config.
    Returns list of tool schemas ready for the Claude API tools parameter.
    """
    allowed = DEFAULT_TOOLS[:]

    if instance and instance.get('config'):
        config = instance['config']
        if isinstance(config, str):
            config = json.loads(config)
        extra = config.get('allowed_tools', [])
        allowed.extend(extra)

    tools = []
    seen = set()
    for name in allowed:
        if name in TOOL_DEFINITIONS and name not in seen:
            tools.append(TOOL_DEFINITIONS[name])
            seen.add(name)

    return tools


# --- Tool execution ---

def execute_tool(
    tool_name: str,
    tool_input: Dict,
    workspace_id: str,
    org_id: Optional[int] = None
) -> str:
    """
    Execute a tool and return the result as a string.
    This is the framework's tool runner — called in the agentic loop
    when Claude returns a tool_use block.
    """
    try:
        if tool_name == "search_knowledge_base":
            return _exec_search_kb(tool_input, org_id)
        elif tool_name == "search_slack_history":
            return _exec_search_slack(tool_input, workspace_id)
        elif tool_name == "lookup_contact":
            return _exec_lookup_contact(tool_input, org_id)
        elif tool_name == "abra":
            return _exec_abra(tool_input)
        elif tool_name == "odoo_cli":
            return _exec_odoo_cli(tool_input)
        elif tool_name == "mcp_taiga":
            return _exec_mcp_taiga(tool_input)
        else:
            return f"Unknown tool: {tool_name}"
    except Exception as e:
        logger.error(f"Tool {tool_name} failed: {e}", exc_info=True)
        return f"Error: {str(e)}"


def _exec_search_kb(tool_input: Dict, org_id: Optional[int]) -> str:
    """Search the knowledge base (abra content via pgvector)."""
    from src.services.binding_service import BindingService
    svc = BindingService(org_id)
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


def _exec_search_slack(tool_input: Dict, workspace_id: str) -> str:
    """Search Slack message history via pgvector."""
    from src.services.query_service import QueryService
    qs = QueryService(workspace_id)
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


def _exec_lookup_contact(tool_input: Dict, org_id: Optional[int]) -> str:
    """Look up a name via binding service (abra)."""
    from src.services.binding_service import BindingService
    svc = BindingService(org_id)
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


def _exec_abra(tool_input: Dict) -> str:
    cmd = tool_input["command"]
    args = tool_input.get("args", "")
    return _exec_cli_tool("abra", f"{cmd} {args}".strip())


def _exec_odoo_cli(tool_input: Dict) -> str:
    cmd = tool_input["command"]
    args = tool_input.get("args", "")
    return _exec_cli_tool("odoo-cli", f"{cmd} {args}".strip())


def _exec_mcp_taiga(tool_input: Dict) -> str:
    cmd = tool_input["command"]
    args = tool_input.get("args", "")
    return _exec_cli_tool("mcp-taiga", f"{cmd} {args}".strip())
