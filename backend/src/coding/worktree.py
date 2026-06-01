"""
Per-session git worktree isolation.

Each coding session gets its own git worktree so concurrent sessions never
collide on a shared working tree. This module only manages worktrees; it does
not run any agent. It is invoked by a real worker once a repo is configured for
a session, and is a no-op concern for the stub worker.

Best-effort and explicit: nothing is created unless a repo path is provided.
"""

import logging
import os
import shutil
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)

# Where per-session worktrees live. Outside any repo, configurable per deployment.
WORKTREE_BASE = os.getenv("CODING_WORKTREE_BASE", "/tmp/amebo-coding-worktrees")


def allocate(session_id: str, repo_path: str, base_ref: str = "HEAD") -> str:
    """
    Create an isolated git worktree for a session on its own branch.

    Returns the worktree path. Raises CalledProcessError if git fails.
    """
    if not repo_path or not os.path.isdir(os.path.join(repo_path, ".git")):
        raise ValueError(f"Not a git repo: {repo_path!r}")

    os.makedirs(WORKTREE_BASE, exist_ok=True)
    path = os.path.join(WORKTREE_BASE, session_id)
    branch = f"coding/{session_id}"

    if os.path.exists(path):
        logger.info("Worktree already present for session %s at %s", session_id, path)
        return path

    subprocess.run(
        ["git", "-C", repo_path, "worktree", "add", "-b", branch, path, base_ref],
        check=True, capture_output=True, text=True,
    )
    logger.info("Allocated worktree for session %s at %s (branch %s)", session_id, path, branch)
    return path


def remove(session_id: str, repo_path: str) -> None:
    """Remove a session's worktree. Best-effort; logs but does not raise."""
    path = os.path.join(WORKTREE_BASE, session_id)
    try:
        if repo_path and os.path.isdir(os.path.join(repo_path, ".git")):
            subprocess.run(
                ["git", "-C", repo_path, "worktree", "remove", "--force", path],
                check=True, capture_output=True, text=True,
            )
        elif os.path.exists(path):
            shutil.rmtree(path, ignore_errors=True)
        logger.info("Removed worktree for session %s", session_id)
    except subprocess.CalledProcessError as e:
        logger.warning("Could not remove worktree for session %s: %s", session_id, e.stderr)
