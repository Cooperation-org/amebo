"""Shared LLM client factory — the one place that decides which provider
(key + endpoint) amebo's conversation/QA/goal paths talk to.

AMEBO_LLM_PROVIDER names the provider we WANT (read per-call, no restart
needed beyond the process picking up .env):

  kimi (default)      — KIMI_API_KEY against KIMI_ANTHROPIC_BASE_URL
                        (Moonshot's Anthropic-compatible endpoint). claude-*
                        model ids do not exist there, so every requested model
                        resolves to KIMI_MODEL (default kimi-k3).
  anthropic           — ANTHROPIC_API_KEY against api.anthropic.com;
                        claude-* model ids pass through unchanged.
  minimax             — MINIMAX_API_KEY against MINIMAX_ANTHROPIC_BASE_URL
                        (MiniMax's Anthropic-compatible endpoint). Same model
                        remapping, via MINIMAX_MODEL (default MiniMax-M3).

Fallback: kimi-k3 is ~10x MiniMax-M3 per token ($3/$15 vs $0.30/$1.26 per
Mtok), so when the wanted provider is failing or has spent a goal's budget
we drop to AMEBO_LLM_FALLBACK_PROVIDER (default minimax) rather than keep
paying or keep erroring. The drop is recorded in the DB and lasts
AMEBO_LLM_TRIP_HOURS (default 24) so one bad hour does not cost a day of
K3 spend, and one recovered minute does not silently put it back. Clear it
with `python scripts/llm_provider.py reset` (or clear_trip()).

Two things trip it:
  - a provider-level failure on messages.create (connection, timeout, 429,
    5xx, 401, 403). A 400/404/422 is our own malformed request — the fallback
    would fail identically, so those never trip and are re-raised untouched.
  - a goal hitting its max_cost_usd guardrail (goal_dispatcher).
A failure that trips also retries that one call on the fallback, so the
request in flight still gets an answer.

Reasoning models put a `thinking` block FIRST in content; kimi-k3 always does
(its API reports supports_thinking_type=only — thinking cannot be disabled).
`response.content[0].text` therefore raises on those providers. Read answer
text with first_text() instead, never by index.

This is the model/key switching described in docs/AMEBO_PREFERENCES.md
section 6; finer-grained per-purpose routing can grow here without touching
call sites again.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import anthropic
from anthropic import Anthropic

logger = logging.getLogger(__name__)

KIMI_DEFAULT_MODEL = "kimi-k3"
KIMI_DEFAULT_BASE_URL = "https://api.moonshot.ai/anthropic"
MINIMAX_DEFAULT_MODEL = "MiniMax-M3"
MINIMAX_DEFAULT_BASE_URL = "https://api.minimax.io/anthropic"

# provider -> (key env var, base-url env var, base-url default, model env var,
#              model default). anthropic is absent: it needs no base_url and
#              passes model ids through unchanged.
_COMPATIBLE_PROVIDERS = {
    "kimi": ("KIMI_API_KEY", "KIMI_ANTHROPIC_BASE_URL", KIMI_DEFAULT_BASE_URL,
             "KIMI_MODEL", KIMI_DEFAULT_MODEL),
    "minimax": ("MINIMAX_API_KEY", "MINIMAX_ANTHROPIC_BASE_URL", MINIMAX_DEFAULT_BASE_URL,
                "MINIMAX_MODEL", MINIMAX_DEFAULT_MODEL),
}

# One row in bot_config (the existing key/value config table, jsonb value)
# holds the trip.
# The DB, not process memory: the scheduler, the API and the Slack listener are
# separate processes and a restart must not hand back the expensive model.
TRIP_CONFIG_KEY = "llm_provider_trip"
DEFAULT_TRIP_HOURS = 24

# Failures that mean the PROVIDER is down or refusing, so the fallback is worth
# trying. APIConnectionError covers APITimeoutError.
_PROVIDER_FAILURES = (
    anthropic.APIConnectionError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
    anthropic.AuthenticationError,
    anthropic.PermissionDeniedError,
)


# ------------------------------------------------------------------ providers

def configured_provider() -> str:
    """The provider we want, before any trip is applied."""
    return os.getenv("AMEBO_LLM_PROVIDER", "kimi").strip().lower()


def fallback_provider() -> str:
    """The cheaper provider to drop to while the wanted one is tripped."""
    return os.getenv("AMEBO_LLM_FALLBACK_PROVIDER", "minimax").strip().lower()


def get_provider() -> str:
    """The provider calls actually go to: the configured one, or the fallback
    while the configured one is tripped."""
    configured = configured_provider()
    trip = read_trip()
    if trip and trip.get("provider") == configured:
        fb = fallback_provider()
        if fb and fb != configured:
            return fb
    return configured


def _model_for(provider: str, requested: str) -> str:
    spec = _COMPATIBLE_PROVIDERS.get(provider)
    if spec:
        _, _, _, model_var, model_default = spec
        return os.getenv(model_var, model_default)
    return requested


def resolve_model(requested: str) -> str:
    """Map a requested model id to one the provider in use actually serves."""
    return _model_for(get_provider(), requested)


def _build_client(provider: str) -> Optional[Anthropic]:
    """Bare SDK client for one provider, or None when its key is missing."""
    spec = _COMPATIBLE_PROVIDERS.get(provider)
    if spec:
        key_var, url_var, url_default, _, _ = spec
        api_key = os.getenv(key_var)
        if not api_key:
            logger.warning("provider %s selected but %s not set", provider, key_var)
            return None
        return Anthropic(api_key=api_key, base_url=os.getenv(url_var, url_default))
    if provider != "anthropic":
        logger.warning("Unknown LLM provider %r, falling back to anthropic", provider)
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set")
        return None
    return Anthropic(api_key=api_key)


def get_llm_client() -> Optional[Anthropic]:
    """Client for the provider in use, or None when its key is missing
    (callers already handle a None client).

    While the configured provider is live the client is wrapped so a
    provider-level failure trips the day-long fallback and retries that call
    on the cheaper provider. Once tripped, the fallback's client is returned
    bare — there is nothing further to fall back to.
    """
    provider = get_provider()
    client = _build_client(provider)
    if client is None:
        return None
    fb = fallback_provider()
    if provider == configured_provider() and fb and fb != provider:
        return _FallbackClient(client, provider)
    return client


# ---------------------------------------------------------------- trip state

def _trip_hours() -> float:
    try:
        return float(os.getenv("AMEBO_LLM_TRIP_HOURS", DEFAULT_TRIP_HOURS))
    except ValueError:
        return float(DEFAULT_TRIP_HOURS)


def read_trip() -> Optional[Dict[str, Any]]:
    """The active trip, or None when there is none or it has expired.

    Never raises: a DB the LLM path cannot reach must not stop LLM calls, it
    just means we cannot see a trip and run on the configured provider.
    """
    from src.db.connection import DatabaseConnection
    conn = None
    try:
        conn = DatabaseConnection.get_connection()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT config_value FROM bot_config WHERE config_key = %s",
                (TRIP_CONFIG_KEY,),
            )
            row = cur.fetchone()
        if not row or not row[0]:
            return None
        # config_value is jsonb: psycopg2 hands back a dict already. A plain
        # string would mean the column type changed under us.
        trip = row[0] if isinstance(row[0], dict) else json.loads(row[0])
        until = datetime.fromisoformat(trip["until"])
        if until <= datetime.now(timezone.utc):
            return None
        return trip
    except Exception:
        logger.debug("Could not read LLM provider trip", exc_info=True)
        return None
    finally:
        if conn is not None:
            DatabaseConnection.return_connection(conn)


def trip_provider(provider: str, reason: str) -> Optional[Dict[str, Any]]:
    """Record that `provider` is not to be used for the next trip window.

    Idempotent within a window: an existing unexpired trip for the same
    provider is left alone, so a burst of failures does not keep pushing the
    expiry out and strand us on the cheap model for a week.
    """
    existing = read_trip()
    if existing and existing.get("provider") == provider:
        return existing
    trip = {
        "provider": provider,
        "fallback": fallback_provider(),
        "reason": reason[:500],
        "since": datetime.now(timezone.utc).isoformat(),
        "until": (datetime.now(timezone.utc) + timedelta(hours=_trip_hours())).isoformat(),
    }
    from src.db.connection import DatabaseConnection
    conn = None
    try:
        conn = DatabaseConnection.get_connection()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO bot_config (config_key, config_value, description, updated_at)
                   VALUES (%s, %s, %s, NOW())
                   ON CONFLICT (config_key) DO UPDATE
                     SET config_value = EXCLUDED.config_value,
                         description  = EXCLUDED.description,
                         updated_at   = NOW()""",
                (TRIP_CONFIG_KEY, json.dumps(trip),
                 "LLM provider dropped to the cheaper fallback until this "
                 "expires; scripts/llm_provider.py reset clears it"),
            )
        conn.commit()
    except Exception:
        logger.exception("Could not record LLM provider trip for %s", provider)
        return None
    finally:
        if conn is not None:
            DatabaseConnection.return_connection(conn)
    logger.warning(
        "LLM provider %s tripped until %s (%s) — calls now go to %s",
        provider, trip["until"], reason, trip["fallback"],
    )
    return trip


def trip_configured_provider(reason: str) -> Optional[Dict[str, Any]]:
    """Trip whatever AMEBO_LLM_PROVIDER names, unless we are already on the
    fallback (nothing to drop to) — for callers that see a cost or failure
    without knowing which provider served it."""
    provider = configured_provider()
    if get_provider() != provider:
        return None
    return trip_provider(provider, reason)


def clear_trip() -> bool:
    """The reset. True when a trip was removed."""
    from src.db.connection import DatabaseConnection
    conn = None
    try:
        conn = DatabaseConnection.get_connection()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM bot_config WHERE config_key = %s", (TRIP_CONFIG_KEY,))
            removed = cur.rowcount > 0
        conn.commit()
        if removed:
            logger.warning("LLM provider trip cleared — back on %s", configured_provider())
        return removed
    except Exception:
        logger.exception("Could not clear LLM provider trip")
        return False
    finally:
        if conn is not None:
            DatabaseConnection.return_connection(conn)


def provider_status() -> Dict[str, Any]:
    """What a human needs to see: wanted provider, provider in use, model, trip."""
    trip = read_trip()
    provider = get_provider()
    return {
        "configured": configured_provider(),
        "in_use": provider,
        "model": _model_for(provider, ""),
        "fallback": fallback_provider(),
        "trip": trip,
    }


# ---------------------------------------------------------- fallback wrapper

class _MessagesWithFallback:
    """messages.create that survives the provider going down: trip, then run
    this one call on the fallback so the request in flight still answers."""

    def __init__(self, messages, provider: str):
        self._messages = messages
        self._provider = provider

    def create(self, **kwargs):
        try:
            return self._messages.create(**kwargs)
        except _PROVIDER_FAILURES as exc:
            fb = fallback_provider()
            client = _build_client(fb) if fb and fb != self._provider else None
            if client is None:
                raise
            trip_provider(self._provider, f"{type(exc).__name__}: {exc}")
            retry = dict(kwargs)
            retry["model"] = _model_for(fb, kwargs.get("model", ""))
            logger.warning(
                "%s failed (%s) — retrying this call on %s/%s",
                self._provider, type(exc).__name__, fb, retry["model"],
            )
            return client.messages.create(**retry)

    def __getattr__(self, name):
        return getattr(self._messages, name)


class _FallbackClient:
    """Anthropic client whose messages.create falls back. Everything else on
    the SDK client passes straight through."""

    def __init__(self, client: Anthropic, provider: str):
        self._client = client
        self.messages = _MessagesWithFallback(client.messages, provider)

    def __getattr__(self, name):
        return getattr(self._client, name)


# ------------------------------------------------------------ response text

def first_text(response) -> str:
    """The answer text of a response, skipping thinking/tool_use blocks.

    Never index into content: a reasoning model (kimi-k3 always, MiniMax-M2)
    puts its thinking block at position 0 and that block has no .text.
    """
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) == "text":
            return block.text
    return ""
