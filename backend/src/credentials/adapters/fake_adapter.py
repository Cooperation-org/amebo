"""
Fake adapter — used only by tests. Lets the resolver be exercised end
to end without hitting any real OAuth provider.

`refresh()` returns a deterministic token based on the input payload.
`exchange_code()` and `build_authorize_url()` work the same way.

The adapter is always registered. Production code never references it
unless it sees `kind="fake"`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from src.credentials.adapters.base import Adapter, RefreshedTokens, register_adapter


class FakeAdapter:
    kind = "fake"

    def refresh(self, payload: Dict[str, Any]) -> RefreshedTokens:
        # Predictable refresh: append "-r" to the previous access_token
        # and push the expiry an hour out.
        prior = payload.get("access_token", "fake-token")
        return RefreshedTokens(
            access_token=prior + "-r",
            refresh_token=payload.get("refresh_token", "fake-refresh"),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

    def build_authorize_url(self, state, scopes, redirect_uri):
        return f"https://fake.example/authorize?state={state}&scope={'+'.join(scopes)}&redirect_uri={redirect_uri}"

    def exchange_code(self, code, redirect_uri):
        return RefreshedTokens(
            access_token=f"fake-token-from-{code}",
            refresh_token="fake-refresh",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )


register_adapter(FakeAdapter())
