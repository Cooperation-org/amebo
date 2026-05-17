"""
Connect-link minting and consumption.

Backs the chat-initiated OAuth flow: a user message asks the claw to do
something that needs a provider credential, amebo mints a short URL,
sends it through the channel adapter, the user clicks it later.

Stays inside the credentials package — endpoints in api/routes/
delegate here.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from psycopg2 import extras

from src.db.connection import DatabaseConnection

logger = logging.getLogger(__name__)


DEFAULT_TTL = timedelta(minutes=15)
SHORT_CODE_BYTES = 16  # ~22 url-safe chars


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ConnectLinkError(RuntimeError):
    """Generic problem with a connect link (not found, consumed, expired)."""


# ---------------------------------------------------------------------------
# Data shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConnectLink:
    short_code: str
    org_id: int
    kind: str
    label: str
    requested_scopes: tuple[str, ...]
    reply_channel: Optional[str]
    requested_by_user_id: Optional[int]
    expires_at: datetime
    consumed_at: Optional[datetime]
    consumed_by_user_id: Optional[int]
    created_at: datetime

    @property
    def is_consumed(self) -> bool:
        return self.consumed_at is not None

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= datetime.now(timezone.utc)

    @property
    def is_usable(self) -> bool:
        return not (self.is_consumed or self.is_expired)


def _row_to_link(row: Dict[str, Any]) -> ConnectLink:
    return ConnectLink(
        short_code=row["short_code"],
        org_id=row["org_id"],
        kind=row["kind"],
        label=row.get("label", "default"),
        requested_scopes=tuple(row.get("requested_scopes") or ()),
        reply_channel=row.get("reply_channel"),
        requested_by_user_id=row.get("requested_by_user_id"),
        expires_at=_aware(row["expires_at"]),
        consumed_at=_aware(row.get("consumed_at")),
        consumed_by_user_id=row.get("consumed_by_user_id"),
        created_at=_aware(row["created_at"]),
    )


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Mint / fetch / consume
# ---------------------------------------------------------------------------


def mint_connect_link(
    org_id: int,
    kind: str,
    requested_scopes: List[str],
    reply_channel: Optional[str] = None,
    requested_by_user_id: Optional[int] = None,
    label: str = "default",
    ttl: timedelta = DEFAULT_TTL,
) -> ConnectLink:
    """
    Mint a fresh single-use connect link. The caller is responsible for
    delivering the link (via channel adapter or HTTP response).
    """
    DatabaseConnection.initialize_pool()
    short_code = secrets.token_urlsafe(SHORT_CODE_BYTES)
    expires_at = datetime.now(timezone.utc) + ttl

    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO connect_links (
                    short_code, org_id, kind, label, requested_scopes,
                    reply_channel, requested_by_user_id, expires_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    short_code,
                    org_id,
                    kind,
                    label,
                    list(requested_scopes),
                    reply_channel,
                    requested_by_user_id,
                    expires_at,
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return _row_to_link(dict(row))
    finally:
        DatabaseConnection.return_connection(conn)


def get_connect_link(short_code: str) -> ConnectLink:
    """Fetch a link by short_code. Raises ConnectLinkError if missing."""
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM connect_links WHERE short_code = %s",
                (short_code,),
            )
            row = cur.fetchone()
            if row is None:
                raise ConnectLinkError("Connect link not found.")
            return _row_to_link(dict(row))
    finally:
        DatabaseConnection.return_connection(conn)


def consume_connect_link(
    short_code: str,
    consumed_by_user_id: Optional[int] = None,
) -> ConnectLink:
    """
    Mark a link as consumed under a row lock. Atomic: a second concurrent
    attempt sees the consumed_at and gets a ConnectLinkError("already
    consumed").
    """
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM connect_links WHERE short_code = %s FOR UPDATE",
                (short_code,),
            )
            row = cur.fetchone()
            if row is None:
                raise ConnectLinkError("Connect link not found.")

            link = _row_to_link(dict(row))
            if link.is_consumed:
                raise ConnectLinkError("Connect link has already been used.")
            if link.is_expired:
                raise ConnectLinkError("Connect link has expired.")

            cur.execute(
                """
                UPDATE connect_links
                SET consumed_at = NOW(), consumed_by_user_id = %s
                WHERE short_code = %s
                RETURNING *
                """,
                (consumed_by_user_id, short_code),
            )
            updated = cur.fetchone()
            conn.commit()
            return _row_to_link(dict(updated))
    finally:
        DatabaseConnection.return_connection(conn)
