"""
Data access for instance configuration.
Each instance is a deployment with its own identity, skills, and knowledge config.
"""

import logging
from typing import Dict, Optional
from psycopg2 import extras
from src.db.connection import DatabaseConnection

logger = logging.getLogger(__name__)


class InstanceRepo:

    def __init__(self):
        DatabaseConnection.initialize_pool()

    def get_by_slug(self, slug: str) -> Optional[Dict]:
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM instances WHERE slug = %s", (slug,))
                row = cur.fetchone()
                return dict(row) if row else None
        finally:
            DatabaseConnection.return_connection(conn)

    def get_by_id(self, instance_id: int) -> Optional[Dict]:
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM instances WHERE id = %s", (instance_id,))
                row = cur.fetchone()
                return dict(row) if row else None
        finally:
            DatabaseConnection.return_connection(conn)

    def create(
        self,
        name: str,
        slug: str,
        identity_prompt: Optional[str] = None,
        config: Optional[Dict] = None,
        org_id: Optional[int] = None
    ) -> Dict:
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO instances (name, slug, identity_prompt, config, org_id)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING *
                """, (name, slug, identity_prompt, extras.Json(config or {}), org_id))
                row = cur.fetchone()
                conn.commit()
                return dict(row)
        finally:
            DatabaseConnection.return_connection(conn)

    def update(self, instance_id: int, **kwargs) -> Optional[Dict]:
        """Update instance fields. Only updates provided kwargs."""
        if not kwargs:
            return self.get_by_id(instance_id)

        conn = DatabaseConnection.get_connection()
        try:
            sets = []
            params = []
            for key in ('name', 'identity_prompt', 'skills_config',
                        'knowledge_config', 'config', 'org_id'):
                if key in kwargs:
                    val = kwargs[key]
                    if key in ('skills_config', 'knowledge_config', 'config'):
                        val = extras.Json(val)
                    sets.append(f"{key} = %s")
                    params.append(val)

            if not sets:
                return self.get_by_id(instance_id)

            sets.append("updated_at = NOW()")
            params.append(instance_id)

            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(f"""
                    UPDATE instances SET {', '.join(sets)}
                    WHERE id = %s RETURNING *
                """, params)
                row = cur.fetchone()
                conn.commit()
                return dict(row) if row else None
        finally:
            DatabaseConnection.return_connection(conn)

    def get_by_slug_and_org(self, slug: str, org_id: int) -> Optional[Dict]:
        """Get an instance by slug, only if it belongs to the given org."""
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM instances WHERE slug = %s AND org_id = %s",
                    (slug, org_id)
                )
                row = cur.fetchone()
                return dict(row) if row else None
        finally:
            DatabaseConnection.return_connection(conn)
