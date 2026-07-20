"""
Read access to organization identity metadata (slug / name / aliases) used by
OrgResolver for explicit-targeting match (arch §4.2 step 4). aliases is mirrored
from the org.yaml manifest (WP3); seeded directly until then.
"""

import logging
from typing import Dict, List, Optional
from psycopg2 import extras
from src.db.connection import DatabaseConnection

logger = logging.getLogger(__name__)


class OrgRepo:

    def __init__(self):
        DatabaseConnection.initialize_pool()

    def metadata(self, org_ids: List[int]) -> List[Dict]:
        """For the given org ids, return {org_id, slug, name, aliases} rows.
        aliases is always a Python list (TEXT[] NULL/'{}' -> [])."""
        if not org_ids:
            return []
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT org_id,
                           org_slug AS slug,
                           org_name AS name,
                           COALESCE(aliases, '{}') AS aliases
                    FROM organizations
                    WHERE org_id = ANY(%s)
                    ORDER BY org_id
                    """,
                    (list(org_ids),),
                )
                out = []
                for r in cur.fetchall():
                    d = dict(r)
                    d["aliases"] = list(d["aliases"] or [])
                    out.append(d)
                return out
        finally:
            DatabaseConnection.return_connection(conn)

    def get(self, org_id: int) -> Optional[Dict]:
        rows = self.metadata([org_id])
        return rows[0] if rows else None

    def set_aliases(self, org_id: int, aliases: List[str]) -> None:
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                # aliases is TEXT[] (schema.sql / migration 029) — a plain
                # Python list adapts to a Postgres array; Json() wrote jsonb.
                cur.execute(
                    "UPDATE organizations SET aliases = %s WHERE org_id = %s",
                    (list(aliases), org_id),
                )
                conn.commit()
        finally:
            DatabaseConnection.return_connection(conn)
