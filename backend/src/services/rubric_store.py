"""Read and write an org's rubric in ``instances.config.rubric``.

One home for the fact (BOUNDARIES: an org's config is its instance row). The
API route and the ``set_rubric`` tool both come through here."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from psycopg2 import extras

from src.db.connection import DatabaseConnection
from src.services.rubric import Rubric

logger = logging.getLogger(__name__)


def read_rubric(org_id: int) -> Rubric:
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT config->'rubric' AS rubric FROM instances "
                "WHERE org_id = %s ORDER BY id LIMIT 1", (org_id,))
            row = cur.fetchone()
            raw = row["rubric"] if row else None
            return Rubric.from_dict(raw) if isinstance(raw, dict) else Rubric()
    finally:
        DatabaseConnection.return_connection(conn)


def write_rubric(org_id: int, changes: Dict[str, Any]) -> Optional[Rubric]:
    """Merge ``changes`` over the org's current rubric and store the result.
    Returns the stored rubric, or None when the org has no instance."""
    current = read_rubric(org_id)
    merged = Rubric.from_dict({**current.to_dict(), **(changes or {})})
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE instances
                SET config = jsonb_set(COALESCE(config, '{}'::jsonb), '{rubric}',
                                       %s::jsonb, true),
                    updated_at = NOW()
                WHERE id = (SELECT id FROM instances WHERE org_id = %s
                            ORDER BY id LIMIT 1)
                RETURNING id
                """,
                (extras.Json(merged.to_dict()), org_id))
            row = cur.fetchone()
            conn.commit()
            return merged if row else None
    except Exception:
        conn.rollback()
        raise
    finally:
        DatabaseConnection.return_connection(conn)
