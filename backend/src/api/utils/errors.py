"""
Error handling utilities for the API.

Provides safe error message formatting that doesn't leak
internal details, file paths, or stack traces to clients.
"""

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Patterns that might leak sensitive info
SENSITIVE_PATTERNS = [
    r'/[a-zA-Z0-9_/.-]+\.py',  # File paths
    r'line \d+',  # Line numbers
    r'File "[^"]+"',  # Python traceback file references
    r'Traceback \(most recent call last\)',  # Traceback headers
    r'password|secret|token|key|credential',  # Sensitive keywords
    r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',  # Email addresses
    r'xox[bpas]-[a-zA-Z0-9-]+',  # Slack tokens
    r'sk-[a-zA-Z0-9]+',  # API keys
]


def sanitize_error_message(error: Exception, default_message: str = "An error occurred") -> str:
    """
    Create a safe error message for API responses.

    Logs the full error internally but returns a sanitized message
    that doesn't leak implementation details.

    Args:
        error: The exception that occurred
        default_message: Default message if error can't be safely exposed

    Returns:
        A safe error message string
    """
    error_str = str(error)

    # Check for sensitive patterns
    for pattern in SENSITIVE_PATTERNS:
        if re.search(pattern, error_str, re.IGNORECASE):
            logger.warning(f"Sanitized error message containing sensitive pattern: {pattern}")
            return default_message

    # Check for common database errors that might leak schema info
    db_error_keywords = [
        'relation', 'column', 'table', 'constraint', 'violates',
        'duplicate key', 'foreign key', 'psycopg2', 'postgresql'
    ]
    if any(keyword in error_str.lower() for keyword in db_error_keywords):
        logger.warning("Sanitized database error message")
        return "A database error occurred"

    # Check for file system errors
    fs_error_keywords = ['permission denied', 'no such file', 'ioerror', 'oserror']
    if any(keyword in error_str.lower() for keyword in fs_error_keywords):
        logger.warning("Sanitized file system error message")
        return "A file system error occurred"

    # Check for network errors
    net_error_keywords = ['connection refused', 'timeout', 'dns', 'socket']
    if any(keyword in error_str.lower() for keyword in net_error_keywords):
        logger.warning("Sanitized network error message")
        return "A network error occurred"

    # If the error message is very long, it might contain a stack trace
    if len(error_str) > 200:
        logger.warning("Sanitized long error message (possible stack trace)")
        return default_message

    # For short, seemingly safe messages, allow them through
    # but still log the full error
    return default_message


def safe_error_response(
    error: Exception,
    operation: str,
    log_error: bool = True
) -> str:
    """
    Generate a safe error response message for a failed operation.

    Args:
        error: The exception that occurred
        operation: Description of what was being attempted (e.g., "create workspace")
        log_error: Whether to log the full error (default True)

    Returns:
        A safe error message like "Failed to create workspace"
    """
    if log_error:
        logger.error(f"Error during {operation}: {error}", exc_info=True)

    # Return a generic message that describes the failed operation
    # but doesn't expose internal error details
    return f"Failed to {operation}"


# Pre-defined safe error messages for common operations
SAFE_ERRORS = {
    'create_workspace': "Failed to create workspace. Please check your credentials and try again.",
    'update_workspace': "Failed to update workspace.",
    'delete_workspace': "Failed to delete workspace.",
    'connection_test': "Connection test failed. Please verify your Slack credentials.",
    'backfill': "Failed to sync messages. Please try again later.",
    'upload': "Failed to upload documents. Please check the file format and try again.",
    'process_question': "Failed to process your question. Please try again.",
    'invite_user': "Failed to send invitation.",
    'database': "A database error occurred. Please try again later.",
    'auth': "Authentication failed.",
}


def get_safe_error(operation: str, fallback: Optional[str] = None) -> str:
    """
    Get a pre-defined safe error message for an operation.

    Args:
        operation: Key for the operation type
        fallback: Fallback message if key not found

    Returns:
        Safe error message
    """
    return SAFE_ERRORS.get(operation, fallback or "An error occurred. Please try again.")
