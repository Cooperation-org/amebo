"""
Credential Helper — the two-authority consumer seam.

This is the ENCAPSULATED boundary that issued OAuth/SSO tokens flow INTO,
and that the rest of amebo (goal dispatcher, tools, claws) asks for a
*capability* — a scoped token or nothing. No call site ever sees a raw
secret, a refresh token, or an "all powerful" token.

----------------------------------------------------------------------
Two kinds of authority (Amebo BOUNDARIES decision, 2026-06-06)
----------------------------------------------------------------------
Amebo acts under exactly one authority per turn:

1. DELEGATED — live, on behalf of a person. Amebo acts AS that person,
   bounded by that person's grant. The tokens belong to the person and
   are retrieved per-turn. Acting identity is the person's author URI
   (``urn:amebo:user:<principal>``).

2. SERVICE / TEAM — background claws. Amebo holds its OWN team-scoped
   service identity (like a bot account), bounded by the team's grant,
   isolated per team. Acting identity is ``amebo:<team>``.

Both live behind ``CredentialHelper``. Storage is swappable behind the
``CredentialStore`` Protocol (env var -> DB -> vault -> KMS -> SSO
broker) without touching any call site.

----------------------------------------------------------------------
Rules enforced here (not just documented)
----------------------------------------------------------------------
* NO god-token. There is no method that returns an unscoped or
  cross-team token. Every accessor is keyed to one authority + one
  (team-or-principal) + one system.
* Per-team / per-principal isolation. A service lookup for team A can
  never return team B's row; a delegated lookup for principal X can
  never return principal Y's row. The lookup key carries the owner, and
  the default store maps it 1:1 onto the existing ``org_credentials``
  unique key ``(org_id, kind, label)``.
* Acting identity is stamped, never inferred downstream. Callers ask the
  helper for it so the same convention is used everywhere.
* ``ScopedToken`` never logs its secret (``__repr__`` redacts it).

----------------------------------------------------------------------
Relationship to the existing ``credentials`` package
----------------------------------------------------------------------
The existing ``CredentialResolver`` / ``client()`` layer already does
per-org encrypted storage, pre-flight refresh, 401 retry and revoke,
keyed on ``(org_id, kind, label)``. This helper does NOT replace it and
does NOT touch any OAuth issuance code. It is an additive façade that:

* expresses the *two-authority* distinction the resolver does not model,
* returns a uniform, secret-safe ``ScopedToken`` capability,
* stamps the acting identity, and
* keeps delegated and service credentials isolated by encoding the owner
  into the resolver's ``label`` (``user:<principal>`` vs ``service``).

The "team" in this module's public API is the org: ``team`` is the
``org_id``. We use the word "team" because that is the BOUNDARIES
vocabulary; internally it is the same integer the resolver expects.
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Authority kinds
# ---------------------------------------------------------------------------

KIND_DELEGATED = "delegated"
KIND_SERVICE = "service"


# Label-namespace convention used by the default (org_credentials-backed)
# store to keep the two authorities isolated within one team's rows.
#
#   delegated person X  ->  label = "user:<principal>"
#   team service        ->  label = "service"
#
# Centralised here so the convention has exactly one definition.
_DELEGATED_LABEL_PREFIX = "user:"
_SERVICE_LABEL = "service"


def _delegated_label(principal: str) -> str:
    return f"{_DELEGATED_LABEL_PREFIX}{principal}"


# ---------------------------------------------------------------------------
# Acting-identity URIs (kept in sync with the conventions already in the
# codebase: urn:amebo:user:<sub> in api/routes/intentions.py, amebo:claw/...
# in intentions_service.py).
# ---------------------------------------------------------------------------

def delegated_author_uri(principal: str) -> str:
    """Author URI for a live turn acting AS a person."""
    return f"urn:amebo:user:{principal}"


def service_author_uri(team: object) -> str:
    """Author URI for a background claw acting as the team's service identity."""
    return f"amebo:{team}"


# ---------------------------------------------------------------------------
# ScopedToken — the only thing call sites receive
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScopedToken:
    """
    A capability: a bearer-usable token value plus the scope/expiry
    metadata needed to reason about it. Deliberately minimal — callers
    must not need to inspect refresh tokens or raw provider blobs.

    Secret safety: the ``value`` is NEVER included in ``repr()`` / ``str``
    so it cannot leak into logs, tracebacks, or ``%r`` formatting. Use
    ``.reveal()`` at the single point where the token is actually placed
    on the wire.
    """

    # Private secret. Underscore + repr=False so dataclass never renders it.
    _value: str = field(repr=False)
    system: str
    scope: tuple[str, ...] = ()
    expires_at: Optional[datetime] = None
    # Who is acting (stamped). Person author URI, or amebo:<team>.
    acting_identity: str = ""
    # Which authority produced this token.
    authority: str = ""

    def reveal(self) -> str:
        """Return the raw token value. Call ONLY when putting it on the wire."""
        return self._value

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return self.expires_at <= datetime.now(timezone.utc)

    def has_scope(self, required: str) -> bool:
        """Fine-grained gate: does this capability include ``required``?"""
        return required in self.scope

    def __repr__(self) -> str:  # noqa: D105 - secret-safe repr
        exp = self.expires_at.isoformat() if self.expires_at else "none"
        return (
            f"ScopedToken(system={self.system!r}, authority={self.authority!r}, "
            f"acting_identity={self.acting_identity!r}, scope={list(self.scope)!r}, "
            f"expires_at={exp}, value=<redacted>)"
        )

    __str__ = __repr__


# ---------------------------------------------------------------------------
# Storage Protocol — swappable backend
# ---------------------------------------------------------------------------


@runtime_checkable
class CredentialStore(Protocol):
    """
    Pluggable storage for issued tokens. Implementations map a fully
    qualified, owner-scoped key to a ``ScopedToken`` (or ``None``).

    Implementations MUST enforce isolation: a lookup for one owner_key
    must never return another owner's secret. They MUST NOT expose any
    method that returns an unscoped / cross-owner token.

    ``owner_key`` is opaque to the store other than as part of the lookup
    key. For the default store it is the org's ``label`` namespace.
    """

    @abstractmethod
    def fetch(
        self,
        *,
        authority: str,
        team: object,
        owner_key: str,
        system: str,
    ) -> Optional[ScopedToken]:
        """Return the scoped token for this exact key, or None if absent."""
        ...


# ---------------------------------------------------------------------------
# Default store: backed by the existing org_credentials / CredentialResolver
# ---------------------------------------------------------------------------


class ResolverCredentialStore:
    """
    Default ``CredentialStore`` that reuses the existing encrypted
    ``org_credentials`` layer via ``CredentialResolver``.

    Isolation: the resolver is keyed ``(org_id, kind, label)``. We set
    ``org_id = team`` and ``label = owner_key`` so:

      * a delegated lookup for principal X uses label ``user:X`` and can
        only ever read X's row,
      * a service lookup for team A uses ``org_id = A`` and can only ever
        read team A's rows.

    There is no code path here that omits the team or the owner from the
    key, so there is no god-token.

    Refresh/expiry/revoke are handled by the resolver; ``CredentialMissing``
    / ``CredentialExpired`` / ``CredentialRevoked`` all surface as ``None``
    from ``fetch`` (the helper treats "no usable capability" uniformly —
    callers that need to mint a connect-link catch the absence and act).
    """

    def fetch(
        self,
        *,
        authority: str,
        team: object,
        owner_key: str,
        system: str,
    ) -> Optional[ScopedToken]:
        # Imported lazily so this module has no hard import-time dependency
        # on the DB layer (keeps unit tests with in-memory stores fast and
        # avoids touching connection pools we don't use).
        from src.credentials.resolver import (
            CredentialResolver,
            CredentialMissing,
            CredentialExpired,
            CredentialRevoked,
        )

        try:
            org_id = int(team)
        except (TypeError, ValueError):
            # team must resolve to an org_id for the default DB store.
            logger.warning("ResolverCredentialStore: non-integer team %r", team)
            return None

        try:
            stored = CredentialResolver(
                org_id=org_id, kind=system, label=owner_key
            ).get()
        except (CredentialMissing, CredentialExpired, CredentialRevoked):
            return None

        if authority == KIND_DELEGATED:
            # owner_key is "user:<principal>" — recover the principal for the
            # acting-identity stamp.
            principal = owner_key[len(_DELEGATED_LABEL_PREFIX):] \
                if owner_key.startswith(_DELEGATED_LABEL_PREFIX) else owner_key
            identity = delegated_author_uri(principal)
        else:
            identity = service_author_uri(team)

        return ScopedToken(
            _value=stored.access_token,
            system=stored.kind,
            scope=tuple(stored.granted_scopes),
            expires_at=stored.expires_at,
            acting_identity=identity,
            authority=authority,
        )


class EnvCredentialStore:
    """
    Env-var-backed ``CredentialStore`` for local/dev and for systems whose
    token is a static service secret injected by the deployment (not an
    OAuth-refreshable token).

    Lookup key -> env var name:

        AMEBO_CRED__<AUTHORITY>__<TEAM>__<OWNER>__<SYSTEM>

    e.g. service token for team 1, system "github":
        AMEBO_CRED__SERVICE__1__SERVICE__GITHUB

    The owner segment keeps the same isolation property as the DB store:
    team A's service var name never matches team B's lookup, and one
    principal's delegated var never matches another's. There is no
    wildcard / "all" var.

    Scopes can be supplied via a sibling var with the ``__SCOPES`` suffix
    (comma-separated); absence means "unknown scope" (empty tuple), which
    a caller can still gate against conservatively.
    """

    PREFIX = "AMEBO_CRED"

    def __init__(self, environ: Optional[dict] = None):
        import os

        self._environ = environ if environ is not None else os.environ

    @staticmethod
    def _seg(value: object) -> str:
        return (
            str(value)
            .upper()
            .replace(":", "_")
            .replace("-", "_")
            .replace(".", "_")
            .replace("/", "_")
        )

    def _var_name(self, authority: str, team: object, owner_key: str, system: str) -> str:
        return "__".join(
            [
                self.PREFIX,
                self._seg(authority),
                self._seg(team),
                self._seg(owner_key),
                self._seg(system),
            ]
        )

    def fetch(
        self,
        *,
        authority: str,
        team: object,
        owner_key: str,
        system: str,
    ) -> Optional[ScopedToken]:
        var = self._var_name(authority, team, owner_key, system)
        value = self._environ.get(var)
        if not value:
            return None

        scopes_raw = self._environ.get(var + "__SCOPES", "")
        scope = tuple(s.strip() for s in scopes_raw.split(",") if s.strip())

        if authority == KIND_DELEGATED:
            principal = owner_key[len(_DELEGATED_LABEL_PREFIX):] \
                if owner_key.startswith(_DELEGATED_LABEL_PREFIX) else owner_key
            identity = delegated_author_uri(principal)
        else:
            identity = service_author_uri(team)

        return ScopedToken(
            _value=value,
            system=system,
            scope=scope,
            expires_at=None,  # static service secrets do not self-expire here
            acting_identity=identity,
            authority=authority,
        )


# ---------------------------------------------------------------------------
# The façade
# ---------------------------------------------------------------------------


class CredentialHelper:
    """
    The single seam the rest of amebo talks to for credentials.

    Construct with one or more ``CredentialStore`` backends; they are
    tried in order and the first hit wins (so a deployment can layer an
    env-injected service secret in front of the DB-backed OAuth store, or
    a vault in front of either, without any call site changing).

    Public API — note there is NO method that returns an unscoped token:

        get_delegated(system, principal) -> ScopedToken | None
        get_service(system, team)        -> ScopedToken | None
        acting_identity(principal=, team=) -> str
    """

    def __init__(self, *stores: CredentialStore):
        if not stores:
            stores = (ResolverCredentialStore(),)
        self._stores = tuple(stores)

    # ------------------------------------------------------------ delegated

    def get_delegated(self, system: str, principal: str) -> Optional[ScopedToken]:
        """
        Capability for a LIVE turn acting AS ``principal`` (a person),
        bounded by that person's grant for ``system``. Returns ``None`` if
        the person has no usable credential (caller mints a connect-link).

        ``principal`` is the person's stable subject (e.g. the value used
        in ``urn:amebo:user:<principal>``). ``team`` is taken from the
        person's org at the call site — see ``get_delegated_for_team`` when
        the org must be specified explicitly.
        """
        raise_if_blank(system, "system")
        raise_if_blank(principal, "principal")
        # Delegated lookups are scoped to a person across whichever team
        # row holds their grant. The default DB store needs an org; callers
        # that have it should use get_delegated_for_team. Here we look up
        # under the principal's own label namespace with the team resolved
        # by the store layer (env store) or supplied explicitly.
        return self._first_hit(
            authority=KIND_DELEGATED,
            team=_principal_team_sentinel(principal),
            owner_key=_delegated_label(principal),
            system=system,
        )

    def get_delegated_for_team(
        self, system: str, principal: str, team: object
    ) -> Optional[ScopedToken]:
        """
        Delegated capability, with the team (org) given explicitly. This is
        the form the DB-backed store needs, since ``org_credentials`` is
        keyed by org. Isolation is enforced by the (team, principal) key.
        """
        raise_if_blank(system, "system")
        raise_if_blank(principal, "principal")
        return self._first_hit(
            authority=KIND_DELEGATED,
            team=team,
            owner_key=_delegated_label(principal),
            system=system,
        )

    # -------------------------------------------------------------- service

    def get_service(self, system: str, team: object) -> Optional[ScopedToken]:
        """
        Capability for a BACKGROUND claw acting as the team's OWN service
        identity, bounded by the team's grant for ``system`` and isolated
        per team. Returns ``None`` if the team has no service credential
        for ``system``.

        A service lookup for team A can never return team B's row: the team
        is part of the lookup key in every store.
        """
        raise_if_blank(system, "system")
        if team is None:
            raise ValueError("get_service requires a team")
        return self._first_hit(
            authority=KIND_SERVICE,
            team=team,
            owner_key=_SERVICE_LABEL,
            system=system,
        )

    # ------------------------------------------------------ acting identity

    def acting_identity(
        self, principal: Optional[str] = None, team: object = None
    ) -> str:
        """
        The stamped acting identity for the current turn.

        * If ``principal`` is given -> delegated: ``urn:amebo:user:<principal>``.
        * Else if ``team`` is given -> service: ``amebo:<team>``.

        Exactly one must be provided; passing both is ambiguous (a turn is
        either delegated OR service, never both) and raises.
        """
        if principal and team is not None:
            raise ValueError(
                "acting_identity is delegated OR service, not both: "
                "pass principal (delegated) or team (service), not both."
            )
        if principal:
            return delegated_author_uri(principal)
        if team is not None:
            return service_author_uri(team)
        raise ValueError("acting_identity requires either principal or team")

    # ------------------------------------------------------------- internal

    def _first_hit(
        self,
        *,
        authority: str,
        team: object,
        owner_key: str,
        system: str,
    ) -> Optional[ScopedToken]:
        for store in self._stores:
            tok = store.fetch(
                authority=authority,
                team=team,
                owner_key=owner_key,
                system=system,
            )
            if tok is not None:
                return tok
        return None


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def raise_if_blank(value: str, name: str) -> None:
    if not value or not str(value).strip():
        raise ValueError(f"{name} is required and must be non-empty")


class _PrincipalTeam:
    """
    Sentinel team for a principal-only delegated lookup. Carries the
    principal so env-style stores can still build a unique, isolated key,
    while signalling to the DB store that no concrete org was supplied
    (the DB store needs an org and will decline -> None, pushing the
    caller to ``get_delegated_for_team``).
    """

    __slots__ = ("principal",)

    def __init__(self, principal: str):
        self.principal = principal

    def __str__(self) -> str:
        return f"principal:{self.principal}"

    def __repr__(self) -> str:
        return f"_PrincipalTeam({self.principal!r})"


def _principal_team_sentinel(principal: str) -> _PrincipalTeam:
    return _PrincipalTeam(principal)
