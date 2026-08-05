"""Who is looking at the list, in the systems the list reads from.

Golda: "i only need see tasks assigned to me, or that need my review."
Answering that needs one fact amebo did not have — which Taiga account belongs
to the person signed in.

Where that fact lives, and why here:

  Who a person IS, and their ids in other systems, belong to abra (BOUNDARIES).
  Abra holds ``taiga:username/<name>`` on each person and amebo reads it there.

  The link from an amebo LOGIN to that person is amebo's own fact — amebo owns
  its users, and abra refuses to store an email address at all (it rejects them
  as PII, on purpose). So the login side of the map lives in the instance's
  ``config.taiga_identities``, which is per-team config read fresh on every
  request. Config, not code: adding a teammate never needs a deploy.

An unmapped viewer gets no filtering rather than an empty list — seeing too much
is a nuisance, seeing nothing looks like the product is broken.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def identity_in(system: str, client: Dict[str, Any],
                instance_config: Optional[Dict[str, Any]]) -> Optional[str]:
    """The viewer's account name in ``system``, or None when nobody has mapped
    them yet.

    One map per system, all of them ``config.<system>_identities`` keyed by the
    amebo login: ``taiga_identities`` -> a Taiga username, ``crm_identities`` ->
    an Odoo login. Same shape for every source the list grows, so adding one is
    config, not code.

    ``client`` is what the auth dependency handed the route. A service key is
    not a person and never gets a personal list.
    """
    if client.get("auth") != "user":
        return None
    email = (client.get("email") or "").strip().lower()
    if not email:
        return None
    mapping = (instance_config or {}).get(f"{system}_identities") or {}
    account = mapping.get(email)
    if not account:
        logger.info("work-list: no %s identity mapped for %s — showing "
                    "everything rather than an empty list", system, email)
    return account


def viewer_person(client: Dict[str, Any]) -> Optional[str]:
    """Who the reader is, as amebo knows them: their login email, lowercased.

    The key anything personal is stored under — pins, burials — and the same key
    the identity maps are written against, so one person has one key across all
    of it. A service key is not a person and gets None, which is what keeps a
    machine from inheriting somebody's pins.
    """
    if client.get("auth") != "user":
        return None
    return (client.get("email") or "").strip().lower() or None


def taiga_username(client: Dict[str, Any],
                   instance_config: Optional[Dict[str, Any]]) -> Optional[str]:
    return identity_in("taiga", client, instance_config)


def crm_logins(client: Dict[str, Any],
               instance_config: Optional[Dict[str, Any]]) -> List[str]:
    """The viewer's Odoo logins. A list, because one human can hold more than
    one account in the same CRM (an ``admin`` login and a named one), and work
    scheduled on either is still theirs. ``crm_identities`` accepts a single
    login or a list of them."""
    mapped = identity_in("crm", client, instance_config)
    if not mapped:
        return []
    return [mapped] if isinstance(mapped, str) else list(mapped)
