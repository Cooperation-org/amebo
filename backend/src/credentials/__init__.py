"""
Credentials package — encapsulated per-org OAuth credentials.

PUBLIC SURFACE (the only things tool code should import):
    from src.credentials import client, CredentialMissing, CredentialExpired

Everything else (storage layout, encryption, refresh logic, provider
adapters) is private. Tool code must NOT import from sub-modules
directly — when we change encryption library, or add a provider, or
migrate to KMS, tool code stays untouched.

The resolver is the ONLY place that touches `org_credentials` rows or
decrypts tokens. Adapters are the ONLY places that talk to provider
OAuth endpoints.
"""

from src.credentials.resolver import (
    CredentialResolver,
    CredentialMissing,
    CredentialExpired,
    CredentialRevoked,
    StoredCredential,
)
from src.credentials.client import client
from src.credentials.connect import (
    ConnectLink,
    ConnectLinkError,
    mint_connect_link,
    get_connect_link,
    consume_connect_link,
)
from src.credentials.credential_helper import (
    CredentialHelper,
    CredentialStore,
    ResolverCredentialStore,
    EnvCredentialStore,
    ScopedToken,
    KIND_DELEGATED,
    KIND_SERVICE,
    delegated_author_uri,
    service_author_uri,
)


__all__ = [
    "CredentialResolver",
    "CredentialMissing",
    "CredentialExpired",
    "CredentialRevoked",
    "StoredCredential",
    "client",
    "ConnectLink",
    "ConnectLinkError",
    "mint_connect_link",
    "get_connect_link",
    "consume_connect_link",
    # Two-authority consumer seam
    "CredentialHelper",
    "CredentialStore",
    "ResolverCredentialStore",
    "EnvCredentialStore",
    "ScopedToken",
    "KIND_DELEGATED",
    "KIND_SERVICE",
    "delegated_author_uri",
    "service_author_uri",
]
