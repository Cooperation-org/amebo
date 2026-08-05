"""
The `/task` command body, parsed. Channel-neutral.

Slack and Discord both offer `/task` and it means the same thing in each: the
human typed exactly what they want, so it is created immediately rather than
routed through the AI loop and the approval gate. Only the parsing lives here —
who is allowed to run it, and how the result is shown, belong to the channel.
"""

TASK_USAGE = (
    "Usage: `/task <project> <subject…> due:YYYY-MM-DD [assign:username] [cash:N]`\n"
    "Example: `/task amebo Ship the badge embed due:2026-06-20 assign:golda cash:50`\n"
    "A deadline (`due:`) is required. The task is created immediately as amebo."
)

# Kept under its old private name for callers that already import it.
_TASK_USAGE = TASK_USAGE


def parse_task_command(text):
    """Parse a `/task` command body into a create payload.

    Format: ``<project> <subject words…> due:YYYY-MM-DD [assign:user] [cash:N]``.
    The first token is the project; key:value tokens (due:/assign:/cash:) may
    appear anywhere after it; everything else is the subject. Returns
    (payload, error_message) — exactly one is None.
    """
    tokens = (text or "").split()
    if len(tokens) < 2:
        return None, TASK_USAGE
    project = tokens[0]
    due = assignee = cash = None
    subject_words = []
    for t in tokens[1:]:
        low = t.lower()
        if low.startswith("due:"):
            due = t[4:]
        elif low.startswith("assign:"):
            assignee = t[7:]
        elif low.startswith("cash:"):
            cash = t[5:]
        else:
            subject_words.append(t)
    subject = " ".join(subject_words).strip()
    if not subject:
        return None, "Missing task subject.\n\n" + TASK_USAGE
    if not due:
        return None, "A deadline is required.\n\n" + TASK_USAGE
    from src.tools.gated_actuators import _valid_due_date
    if not _valid_due_date(due):
        return None, f"`{due}` is not a valid date — use YYYY-MM-DD.\n\n" + TASK_USAGE
    payload = {"project": project, "subject": subject, "due_date": due}
    if assignee:
        payload["assignee"] = assignee
    if cash is not None:
        if not cash.isdigit():
            return None, f"`cash:{cash}` must be a number.\n\n" + TASK_USAGE
        payload["cash"] = int(cash)
    return payload, None
