"""
Data access layer for structured knowledge (bindings, content, hot tags).

Reads from abra's database when ABRA_DATABASE_URL is configured.
Abra tables: content, bindings, hot_tags (no prefix, no org_id).

Falls back to local amebo tables (abra_* prefix, with org_id) if abra
connection is not available.
"""

import logging
from typing import List, Dict, Optional
from psycopg2 import extras

from src.db.abra_connection import AbraConnection
from src.db.connection import DatabaseConnection

logger = logging.getLogger(__name__)


class BindingRepo:
    """Data access for bindings, content, and hot tags."""

    def __init__(self, org_id: int = None):
        self.org_id = org_id
        self._use_abra = AbraConnection.is_available()
        if not self._use_abra:
            DatabaseConnection.initialize_pool()

    def _get_conn(self):
        """Get connection from the appropriate pool."""
        if self._use_abra:
            return AbraConnection.get_connection()
        return DatabaseConnection.get_connection()

    def _return_conn(self, conn):
        if self._use_abra:
            AbraConnection.return_connection(conn)
        else:
            DatabaseConnection.return_connection(conn)

    # Table names differ between abra DB and local amebo DB
    @property
    def _t_bindings(self):
        return "bindings" if self._use_abra else "abra_bindings"

    @property
    def _t_content(self):
        return "content" if self._use_abra else "abra_content"

    @property
    def _t_hot_tags(self):
        return "hot_tags" if self._use_abra else "abra_hot_tags"

    def _org_filter(self):
        """Return org_id WHERE clause fragment (empty for abra, which has no org_id)."""
        if self._use_abra:
            return "", []
        return "org_id = %s AND ", [self.org_id]

    def search_bindings_by_name(
        self,
        name: str,
        scope: Optional[str] = None,
        workspace_id: Optional[str] = None
    ) -> List[Dict]:
        """Find all bindings for a name (case-insensitive)."""
        conn = self._get_conn()
        if not conn:
            return []
        try:
            org_clause, org_params = self._org_filter()
            conditions = [f"{org_clause}LOWER(name) = LOWER(%s)"]
            params = org_params + [name]

            if scope:
                conditions.append("scope = %s")
                params.append(scope)
            if workspace_id and not self._use_abra:
                conditions.append("(workspace_id = %s OR workspace_id IS NULL)")
                params.append(workspace_id)

            where = " AND ".join(conditions)

            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(f"""
                    SELECT id, scope, name, relationship, target_type,
                           target_ref, qualifier, permanence, source_date
                    FROM {self._t_bindings}
                    WHERE {where}
                    ORDER BY relationship, name
                """, params)
                return cur.fetchall()
        finally:
            self._return_conn(conn)

    def search_bindings_by_names(
        self,
        names: List[str],
        scope: Optional[str] = None
    ) -> List[Dict]:
        """Find bindings for multiple names at once (batch lookup)."""
        if not names:
            return []
        conn = self._get_conn()
        if not conn:
            return []
        try:
            lower_names = [n.lower() for n in names]
            org_clause, org_params = self._org_filter()
            conditions = [f"{org_clause}LOWER(name) = ANY(%s)"]
            params = org_params + [lower_names]

            if scope:
                conditions.append("scope = %s")
                params.append(scope)

            where = " AND ".join(conditions)

            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(f"""
                    SELECT id, scope, name, relationship, target_type,
                           target_ref, qualifier, permanence, source_date
                    FROM {self._t_bindings}
                    WHERE {where}
                    ORDER BY name, relationship
                """, params)
                return cur.fetchall()
        finally:
            self._return_conn(conn)

    def who(self, term: str, scope: Optional[str] = None) -> List[Dict]:
        """Find people/names by topic keyword (searches qualifier and target_ref)."""
        conn = self._get_conn()
        if not conn:
            return []
        try:
            org_clause, org_params = self._org_filter()
            params = org_params + [f"%{term}%", f"%{term}%"]
            scope_clause = ""
            if scope:
                scope_clause = "AND b.scope = %s"
                params.append(scope)

            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(f"""
                    SELECT DISTINCT b.name, b.qualifier, b.source_date
                    FROM {self._t_bindings} b
                    WHERE {org_clause}(b.qualifier ILIKE %s OR b.target_ref ILIKE %s)
                    {scope_clause}
                    ORDER BY b.name
                """, params)
                return cur.fetchall()
        finally:
            self._return_conn(conn)

    def get_hot_tags(self, scope: Optional[str] = None) -> List[Dict]:
        """Get hot tags (priority items)."""
        conn = self._get_conn()
        if not conn:
            return []
        try:
            org_clause, org_params = self._org_filter()
            conditions = [f"{org_clause}(expires_at IS NULL OR expires_at > NOW())"]
            params = org_params[:]

            if scope:
                conditions.append("scope = %s")
                params.append(scope)

            where = " AND ".join(conditions)

            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(f"""
                    SELECT scope, name, priority, added_at, expires_at
                    FROM {self._t_hot_tags}
                    WHERE {where}
                    ORDER BY priority DESC, added_at DESC
                """, params)
                return cur.fetchall()
        finally:
            self._return_conn(conn)

    def is_hot(self, name: str, scope: Optional[str] = None) -> bool:
        """Check if a name is a hot tag."""
        conn = self._get_conn()
        if not conn:
            return False
        try:
            org_clause, org_params = self._org_filter()
            conditions = [f"{org_clause}LOWER(name) = LOWER(%s)",
                         "(expires_at IS NULL OR expires_at > NOW())"]
            params = org_params + [name]

            if scope:
                conditions.append("scope = %s")
                params.append(scope)

            where = " AND ".join(conditions)

            with conn.cursor() as cur:
                cur.execute(f"SELECT 1 FROM {self._t_hot_tags} WHERE {where} LIMIT 1", params)
                return cur.fetchone() is not None
        finally:
            self._return_conn(conn)

    def get_content(self, content_id: int) -> Optional[Dict]:
        """Get a content blob by ID."""
        conn = self._get_conn()
        if not conn:
            return None
        try:
            org_clause, org_params = self._org_filter()
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(f"""
                    SELECT id, source_file, content, note_date, catcode, created_at
                    FROM {self._t_content}
                    WHERE {org_clause}id = %s
                """, org_params + [content_id])
                return cur.fetchone()
        finally:
            self._return_conn(conn)

    def search_content(self, query: str, scope: Optional[str] = None, limit: int = 10) -> List[Dict]:
        """Search content by text (uses embedding similarity if available)."""
        conn = self._get_conn()
        if not conn:
            return []
        try:
            from src.db.embedding import embed_text
            query_embedding = embed_text(query)

            org_clause, org_params = self._org_filter()
            params = org_params + [query_embedding, query_embedding, limit]

            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(f"""
                    SELECT id, source_file, content, note_date, catcode,
                           1 - (embedding <=> %s::vector) AS similarity
                    FROM {self._t_content}
                    WHERE {org_clause}embedding IS NOT NULL
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                """, params)
                return cur.fetchall()
        except Exception as e:
            logger.warning(f"Content search failed: {e}")
            return []
        finally:
            self._return_conn(conn)

    # --- Write operations (always use local amebo tables) ---

    def _get_local_conn(self):
        """Get connection to local amebo DB for writes."""
        DatabaseConnection.initialize_pool()
        return DatabaseConnection.get_connection()

    def create_binding(
        self,
        scope: str,
        name: str,
        relationship: str,
        target_type: str,
        target_ref: str,
        qualifier: Optional[str] = None,
        permanence: str = 'CURRENT',
        source_date=None,
        workspace_id: Optional[str] = None,
        catcode: Optional[str] = None
    ) -> int:
        """Create a new binding in local amebo DB. Returns binding ID."""
        conn = self._get_local_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO abra_bindings
                        (org_id, workspace_id, scope, name, relationship,
                         target_type, target_ref, qualifier, permanence,
                         source_date, catcode)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    self.org_id, workspace_id, scope, name, relationship,
                    target_type, target_ref, qualifier, permanence,
                    source_date, catcode
                ))
                binding_id = cur.fetchone()[0]
                conn.commit()
            return binding_id
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to create binding: {e}")
            raise
        finally:
            DatabaseConnection.return_connection(conn)

    def create_content(
        self,
        content: str,
        source_file: Optional[str] = None,
        note_date=None,
        workspace_id: Optional[str] = None,
        catcode: Optional[str] = None,
        embedding=None
    ) -> int:
        """Create a content blob in local amebo DB. Returns content ID."""
        conn = self._get_local_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO abra_content
                        (org_id, workspace_id, source_file, content,
                         embedding, note_date, catcode)
                    VALUES (%s, %s, %s, %s, %s::vector, %s, %s)
                    RETURNING id
                """, (
                    self.org_id, workspace_id, source_file, content,
                    embedding, note_date, catcode
                ))
                content_id = cur.fetchone()[0]
                conn.commit()
            return content_id
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to create content: {e}")
            raise
        finally:
            DatabaseConnection.return_connection(conn)

    def set_hot_tag(
        self,
        scope: str,
        name: str,
        priority: int = 0,
        expires_at=None
    ):
        """Set a hot tag in local amebo DB."""
        conn = self._get_local_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO abra_hot_tags (org_id, scope, name, priority, expires_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (org_id, scope, name)
                    DO UPDATE SET priority = EXCLUDED.priority,
                                  expires_at = EXCLUDED.expires_at,
                                  added_at = NOW()
                """, (self.org_id, scope, name, priority, expires_at))
                conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to set hot tag: {e}")
            raise
        finally:
            DatabaseConnection.return_connection(conn)

    def unset_hot_tag(self, scope: str, name: str):
        """Remove a hot tag from local amebo DB."""
        conn = self._get_local_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    DELETE FROM abra_hot_tags
                    WHERE org_id = %s AND scope = %s AND LOWER(name) = LOWER(%s)
                """, (self.org_id, scope, name))
                conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to unset hot tag: {e}")
            raise
        finally:
            DatabaseConnection.return_connection(conn)
