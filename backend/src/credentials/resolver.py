"""
CredentialResolver — the single point of truth for credential access.

Tool code calls this. No other module reads `org_credentials` or touches
encryption.

Encapsulates:
- Storage (SQL on org_credentials)
- Encryption (Fernet via encryption.py)
- Pre-flight refresh (5-min buffer before expiry)
- DB-level locking during refresh (no concurrent double-refresh)
- Provider differences (delegated to adapters)
- Error normalization (CredentialMissing / Expired / Revoked)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from psycopg2 import extras

from src.credentials import encryption
from src.db.connection import DatabaseConnection

logger = logging.getLogger(__name__)


# How close to expiry should we pre-emptively refresh? Tokens that expire
# within this window are refreshed on get(), before the call is made.
REFRESH_BUFFER = timedelta(minutes=5)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class CredentialMissing(LookupError):
    """No credential of this kind/label exists for the org."""

    def __init__(self, org_id: int, kind: str, label: str = "default"):
        super().__init__(f"No credential: org={org_id} kind={kind} label={label}")
        self.org_id = org_id
        self.kind = kind
        self.label = label


class CredentialExpired(RuntimeError):
    """Refresh token is dead — user must reconnect via OAuth."""

    def __init__(self, org_id: int, kind: str, label: str = "default", reason: str = ""):
        super().__init__(f"Credential expired: org={org_id} kind={kind} label={label}: {reason}")
        self.org_id = org_id
        self.kind = kind
        self.label = label
        self.reason = reason


class CredentialRevoked(RuntimeError):
    """Credential was explicitly revoked (by admin or by provider)."""

    def __init__(self, org_id: int, kind: str, label: str = "default"):
        super().__init__(f"Credential revoked: org={org_id} kind={kind} label={label}")
        self.org_id = org_id
        self.kind = kind
        self.label = label


# ---------------------------------------------------------------------------
# Stored shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StoredCredential:
    """
    Returned by CredentialResolver.get(). Intentionally minimal — callers
    should not need to inspect raw provider fields.

    `access_token` is always present and current (refresh has already
    happened if it was about to expire).
    """
    org_id: int
    kind: str
    label: str
    access_token: str
    expires_at: Optional[datetime]
    granted_scopes: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


class CredentialResolver:
    """
    Thread-safe-ish (DB-level locks for refresh). Instantiate per call;
    the underlying DB pool is shared.
    """

    def __init__(self, org_id: int, kind: str, label: str = "default"):
        self.org_id = org_id
        self.kind = kind
        self.label = label
        DatabaseConnection.initialize_pool()

    # ------------------------------------------------------------ Public

    def get(self) -> StoredCredential:
        """
        Return a current, valid credential. Refreshes pre-flight if needed.

        Raises:
            CredentialMissing — no row exists.
            CredentialRevoked — row exists but is revoked.
            CredentialExpired — refresh token is dead; user must reconnect.
        """
        record = self._fetch_active_row()
        if record is None:
            raise CredentialMissing(self.org_id, self.kind, self.label)
        return self._resolve(record)

    def get_payload(self) -> Dict[str, Any]:
        """
        Return the full decrypted credential payload as a dict — for STATIC
        (non-OAuth) credentials whose shape isn't a single bearer token, e.g.
        Taiga (``{"TAIGA_USERNAME":…, "TAIGA_PASSWORD":…, "TAIGA_URL":…}``) or
        git (``{"repo_url":…, "token":…}``). Static creds don't expire/refresh,
        so this does no refresh — it just decrypts the active row.

        Raises CredentialMissing if there's no active row for this
        (org_id, kind, label). Strictly per-org: it only ever reads this
        resolver's own org_id.
        """
        record = self._fetch_active_row()
        if record is None:
            raise CredentialMissing(self.org_id, self.kind, self.label)
        return encryption.decrypt_json(bytes(record["encrypted_value"]))

    def force_refresh(self) -> StoredCredential:
        """
        Refresh the credential even if it's not yet expired. Used by the
        lazy-401 fallback path after a tool call gets an auth failure.
        """
        return self._refresh(lock_required=True, unconditional=True)

    def mark_used(self) -> None:
        """Bump last_used_at. Best-effort; failures are swallowed."""
        try:
            conn = DatabaseConnection.get_connection()
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE org_credentials SET last_used_at = NOW() "
                    "WHERE org_id = %s AND kind = %s AND label = %s "
                    "AND revoked_at IS NULL",
                    (self.org_id, self.kind, self.label),
                )
                conn.commit()
        except Exception:
            logger.exception("Failed to bump last_used_at")
        finally:
            try:
                DatabaseConnection.return_connection(conn)
            except Exception:
                pass

    # ----------------------------------------------------------- Internal

    def _resolve(self, record: Dict[str, Any]) -> StoredCredential:
        """Decrypt, decide if refresh is needed, return a StoredCredential."""
        payload = encryption.decrypt_json(bytes(record["encrypted_value"]))

        expires_at = record["expires_at"]
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if self._needs_refresh(expires_at):
            return self._refresh(lock_required=True)

        return StoredCredential(
            org_id=self.org_id,
            kind=self.kind,
            label=self.label,
            access_token=payload["access_token"],
            expires_at=expires_at,
            granted_scopes=tuple(record.get("granted_scopes") or ()),
        )

    @staticmethod
    def _needs_refresh(expires_at: Optional[datetime]) -> bool:
        if expires_at is None:
            return False  # provider gave us an unbounded token
        return expires_at - REFRESH_BUFFER <= datetime.now(timezone.utc)

    def _refresh(
        self,
        *,
        lock_required: bool,
        unconditional: bool = False,
    ) -> StoredCredential:
        """
        Perform a refresh under a row-level lock so concurrent callers
        cannot double-refresh the same credential.

        When `unconditional` is False (the default), this function will
        no-op if another worker has already refreshed the credential in
        the meantime — saves a network round-trip.

        When `unconditional` is True (force_refresh path), the refresh
        runs regardless of the current expiry. Use after a 401: the
        server told us the token is bad even if we think it's fresh.

        Delegates provider-specific HTTP to the kind's adapter.
        """
        from src.credentials.adapters import get_adapter

        adapter = get_adapter(self.kind)

        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                # Re-fetch with a row lock so we have authoritative state
                # under contention. If another worker just refreshed, we
                # may not need to refresh at all.
                cur.execute(
                    "SELECT * FROM org_credentials "
                    "WHERE org_id = %s AND kind = %s AND label = %s "
                    "AND revoked_at IS NULL "
                    "FOR UPDATE",
                    (self.org_id, self.kind, self.label),
                )
                row = cur.fetchone()
                if row is None:
                    raise CredentialMissing(self.org_id, self.kind, self.label)

                payload = encryption.decrypt_json(bytes(row["encrypted_value"]))
                current_expires_at = row["expires_at"]
                if current_expires_at is not None and current_expires_at.tzinfo is None:
                    current_expires_at = current_expires_at.replace(tzinfo=timezone.utc)

                # If another worker already refreshed (and we're not forcing),
                # just return the fresh row — no need to burn another call.
                if not unconditional and not self._needs_refresh(current_expires_at):
                    return StoredCredential(
                        org_id=self.org_id,
                        kind=self.kind,
                        label=self.label,
                        access_token=payload["access_token"],
                        expires_at=current_expires_at,
                        granted_scopes=tuple(row.get("granted_scopes") or ()),
                    )

                try:
                    refreshed = adapter.refresh(payload)
                except Exception as exc:
                    # Mark revoked so subsequent gets fail-fast with a
                    # CredentialMissing → connect-link UX.
                    cur.execute(
                        "UPDATE org_credentials SET revoked_at = NOW() "
                        "WHERE id = %s",
                        (row["id"],),
                    )
                    conn.commit()
                    raise CredentialExpired(
                        self.org_id, self.kind, self.label, reason=str(exc),
                    )

                new_payload = {
                    **payload,
                    "access_token": refreshed.access_token,
                }
                if refreshed.refresh_token:
                    new_payload["refresh_token"] = refreshed.refresh_token

                cur.execute(
                    "UPDATE org_credentials "
                    "SET encrypted_value = %s, expires_at = %s, updated_at = NOW() "
                    "WHERE id = %s",
                    (
                        encryption.encrypt_json(new_payload),
                        refreshed.expires_at,
                        row["id"],
                    ),
                )
                conn.commit()

                return StoredCredential(
                    org_id=self.org_id,
                    kind=self.kind,
                    label=self.label,
                    access_token=refreshed.access_token,
                    expires_at=refreshed.expires_at,
                    granted_scopes=tuple(row.get("granted_scopes") or ()),
                )
        finally:
            DatabaseConnection.return_connection(conn)

    def _fetch_active_row(self) -> Optional[Dict[str, Any]]:
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM org_credentials "
                    "WHERE org_id = %s AND kind = %s AND label = %s "
                    "AND revoked_at IS NULL",
                    (self.org_id, self.kind, self.label),
                )
                row = cur.fetchone()
                return dict(row) if row else None
        finally:
            DatabaseConnection.return_connection(conn)

    # -------------------------------------------------------- Admin API

    @classmethod
    def store_new(
        cls,
        org_id: int,
        kind: str,
        access_token: str,
        refresh_token: Optional[str] = None,
        expires_at: Optional[datetime] = None,
        granted_scopes: Optional[list[str]] = None,
        label: str = "default",
        connected_by_user_id: Optional[int] = None,
        extra_payload: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Create or replace a credential. Returns the row id.

        Used by the OAuth callback handler when a fresh token arrives, and
        by tests. Not for tool code.
        """
        payload: Dict[str, Any] = {"access_token": access_token}
        if refresh_token:
            payload["refresh_token"] = refresh_token
        if extra_payload:
            for k, v in extra_payload.items():
                if k not in ("access_token", "refresh_token"):
                    payload[k] = v

        encrypted = encryption.encrypt_json(payload)

        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO org_credentials (
                        org_id, kind, label, encrypted_value,
                        granted_scopes, expires_at, connected_by_user_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (org_id, kind, label) DO UPDATE
                    SET encrypted_value     = EXCLUDED.encrypted_value,
                        granted_scopes      = EXCLUDED.granted_scopes,
                        expires_at          = EXCLUDED.expires_at,
                        connected_by_user_id = EXCLUDED.connected_by_user_id,
                        updated_at           = NOW(),
                        revoked_at           = NULL
                    RETURNING id
                    """,
                    (
                        org_id,
                        kind,
                        label,
                        encrypted,
                        granted_scopes or [],
                        expires_at,
                        connected_by_user_id,
                    ),
                )
                row_id = cur.fetchone()[0]
                conn.commit()
                return row_id
        finally:
            DatabaseConnection.return_connection(conn)

    @classmethod
    def revoke(cls, org_id: int, kind: str, label: str = "default") -> bool:
        """Mark the credential revoked. Returns True if a row was updated."""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE org_credentials SET revoked_at = NOW() "
                    "WHERE org_id = %s AND kind = %s AND label = %s "
                    "AND revoked_at IS NULL",
                    (org_id, kind, label),
                )
                changed = cur.rowcount
                conn.commit()
                return changed > 0
        finally:
            DatabaseConnection.return_connection(conn)

    @classmethod
    def list_for_org(cls, org_id: int) -> list[Dict[str, Any]]:
        """
        Public-safe view of an org's credentials. Never decrypts the blob;
        only exposes metadata for the Connections UI.
        """
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, kind, label, granted_scopes, expires_at,
                           created_at, updated_at, last_used_at, revoked_at
                    FROM org_credentials
                    WHERE org_id = %s
                    ORDER BY kind, label
                    """,
                    (org_id,),
                )
                return [dict(r) for r in cur.fetchall()]
        finally:
            DatabaseConnection.return_connection(conn)


# ---------------------------------------------------------------------------
# Static credential storage (non-OAuth: Taiga user/pass, git token, etc.)
# ---------------------------------------------------------------------------


def store_static(
    org_id: int,
    kind: str,
    payload: Dict[str, Any],
    *,
    label: str = "default",
    granted_scopes: Optional[list] = None,
    connected_by_user_id: Optional[int] = None,
) -> None:
    """
    Store (or replace) a STATIC per-org credential: an encrypted field map for
    systems that don't use OAuth bearer tokens (Taiga, git, API keys). Read back
    with ``CredentialResolver(org_id, kind, label).get_payload()``.

    Replaces any existing active cred for (org_id, kind, label) by revoking it
    and inserting fresh — preserves history via ``revoked_at``, and needs no
    unique constraint. The secret is encrypted at rest (Fernet) and never logged.
    """
    enc = encryption.encrypt_json(payload)
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE org_credentials SET revoked_at = NOW() "
                "WHERE org_id = %s AND kind = %s AND label = %s AND revoked_at IS NULL",
                (org_id, kind, label),
            )
            cur.execute(
                """
                INSERT INTO org_credentials
                    (org_id, kind, label, encrypted_value, granted_scopes, connected_by_user_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (org_id, kind, label, enc, granted_scopes or [], connected_by_user_id),
            )
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)
