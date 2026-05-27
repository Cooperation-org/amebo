"""
Provider adapters — per-OAuth-provider refresh + connect-URL building.

Each adapter conforms to the Adapter protocol in base.py. New providers
add a module here and call register_adapter(); nothing else in amebo
needs to change.
"""

from __future__ import annotations

from src.credentials.adapters.base import (
    Adapter,
    RefreshedTokens,
    get_adapter,
    register_adapter,
)

# Importing modules triggers their register_adapter() calls.
from src.credentials.adapters import fake_adapter  # noqa: F401  (used in tests)
from src.credentials.adapters import google_adapter  # noqa: F401

__all__ = [
    "Adapter",
    "RefreshedTokens",
    "get_adapter",
    "register_adapter",
]
