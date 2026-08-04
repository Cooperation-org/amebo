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
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def taiga_username(client: Dict[str, Any],
                   instance_config: Optional[Dict[str, Any]]) -> Optional[str]:
    """The viewer's Taiga username, or None when nobody has mapped them yet.

    ``client`` is what the auth dependency handed the route. A service key is
    not a person and never gets a personal list.
    """
    if client.get("auth") != "user":
        return None
    email = (client.get("email") or "").strip().lower()
    if not email:
        return None
    mapping = (instance_config or {}).get("taiga_identities") or {}
    username = mapping.get(email)
    if not username:
        logger.info("work-list: no taiga identity mapped for %s — showing "
                    "everything rather than an empty list", email)
    return username
