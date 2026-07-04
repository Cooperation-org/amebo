"""
Data access for recognition — mapping a channel/OIDC identity to a person
(platform_users). See arch §3. Amebo's own auth state; rows are created by
provisioning or an admin-gated linking flow, never inferred from message content.
"""

import logging
from typing import Dict, List, Optional
from psycopg2 import extras
from src.db.connection import DatabaseConnection

logger = logging.getLogger(__name__)


class PersonIdentityRepo:

    def __init__(self):
        DatabaseConnection.initialize_pool()

    def recognize(self, provider: str, external_id: str,
                  context_ref: str = "") -> Optional[int]:
        """Return the person (platform_users.user_id) for an external identity,
        or None if unrecognized. Slack: recognize('slack', 'Uxxxx', team_id).
        OIDC: recognize('oidc', sub, issuer)."""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT user_id FROM person_identities
                    WHERE provider = %s AND context_ref = %s AND external_id = %s
                    """,
                    (provider, context_ref or "", external_id),
                )
                row = cur.fetchone()
                return row[0] if row else None
        finally:
            DatabaseConnection.return_connection(conn)

    def identities_for(self, user_id: int) -> List[Dict]:
        """Every external identity known for a person."""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT provider, context_ref, external_id, verified
                    FROM person_identities WHERE user_id = %s
                    ORDER BY provider, context_ref
                    """,
                    (user_id,),
                )
                return [dict(r) for r in cur.fetchall()]
        finally:
            DatabaseConnection.return_connection(conn)

    def link(self, user_id: int, provider: str, external_id: str,
             context_ref: str = "", verified: bool = True) -> Dict:
        """Idempotently record a recognition mapping (provisioning/admin action).
        On conflict the mapping's person + verified flag are refreshed."""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO person_identities
                        (user_id, provider, context_ref, external_id, verified)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (provider, context_ref, external_id) DO UPDATE
                        SET user_id = EXCLUDED.user_id, verified = EXCLUDED.verified
                    RETURNING user_id, provider, context_ref, external_id, verified
                    """,
                    (user_id, provider, context_ref or "", external_id, verified),
                )
                row = cur.fetchone()
                conn.commit()
                return dict(row)
        finally:
            DatabaseConnection.return_connection(conn)
