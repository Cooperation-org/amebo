"""
Symmetric encryption for credential blobs.

Fernet (authenticated AES-128-CBC + HMAC-SHA256). Lightweight, well-vetted,
zero key-management complexity at this scale.

The key lives in the AMEBO_CRED_KEY environment variable. NEVER in the
database, NEVER in the repo, NEVER in logs.

To generate a key:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Key rotation (future): support a comma-separated list of keys
(AMEBO_CRED_KEY=current,previous) so we can re-encrypt on read with the
new key and retire the old. Not implemented in v1.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

from cryptography.fernet import Fernet, InvalidToken


class CredentialEncryptionError(RuntimeError):
    """Raised when encryption setup is broken (missing key, bad key, etc.)."""


_INSTANCE: "_Cipher | None" = None


class _Cipher:
    """Lazily-constructed cipher wrapper. One process-wide instance."""

    def __init__(self, key: bytes):
        try:
            self._fernet = Fernet(key)
        except (ValueError, TypeError) as exc:
            raise CredentialEncryptionError(
                "AMEBO_CRED_KEY is not a valid Fernet key. Generate one with "
                "`python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"`"
            ) from exc

    def encrypt_json(self, payload: Dict[str, Any]) -> bytes:
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return self._fernet.encrypt(raw)

    def decrypt_json(self, blob: bytes) -> Dict[str, Any]:
        if isinstance(blob, memoryview):
            blob = bytes(blob)
        try:
            raw = self._fernet.decrypt(blob)
        except InvalidToken as exc:
            raise CredentialEncryptionError(
                "Encrypted credential blob could not be decrypted. The "
                "AMEBO_CRED_KEY may have changed since this blob was stored."
            ) from exc
        return json.loads(raw.decode("utf-8"))


def _load_cipher() -> _Cipher:
    """
    Load the cipher from the AMEBO_CRED_KEY env var on first use. After
    that, the instance is reused for the lifetime of the process.

    Refuses to start if the key is missing — we will NOT silently fall
    back to plaintext.
    """
    global _INSTANCE
    if _INSTANCE is None:
        key = os.getenv("AMEBO_CRED_KEY")
        if not key:
            raise CredentialEncryptionError(
                "AMEBO_CRED_KEY environment variable is required for credential "
                "storage. Generate one with: python -c \"from cryptography.fernet "
                "import Fernet; print(Fernet.generate_key().decode())\""
            )
        _INSTANCE = _Cipher(key.encode("utf-8"))
    return _INSTANCE


# ---------------------------------------------------------------------------
# Public surface (used only by the resolver)
# ---------------------------------------------------------------------------


def encrypt_json(payload: Dict[str, Any]) -> bytes:
    return _load_cipher().encrypt_json(payload)


def decrypt_json(blob: bytes) -> Dict[str, Any]:
    return _load_cipher().decrypt_json(blob)


def reset_for_tests() -> None:
    """Drop the cached cipher so tests can swap the env var."""
    global _INSTANCE
    _INSTANCE = None
