#!/usr/bin/env python3
"""
Initialize database with all schemas
Runs schema.sql and schema_auth.sql
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.db.connection import DatabaseConnection
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_sql_file(conn, file_path: str):
    """Execute SQL from file"""
    logger.info(f"Running SQL file: {file_path}")

    with open(file_path, 'r') as f:
        sql = f.read()

    with conn.cursor() as cur:
        cur.execute(sql)

    conn.commit()
    logger.info(f"✅ {file_path} executed successfully")


def main():
    logger.info("Initializing database...")

    DatabaseConnection.initialize_pool()
    conn = DatabaseConnection.get_connection()

    try:
        # Run main schema (Slack data tables)
        schema_path = os.path.join(
            os.path.dirname(__file__),
            '..',
            'src',
            'db',
            'schema.sql'
        )
        run_sql_file(conn, schema_path)

        # Run auth schema (organizations, users, documents)
        auth_schema_path = os.path.join(
            os.path.dirname(__file__),
            '..',
            'src',
            'db',
            'schema_auth.sql'
        )
        run_sql_file(conn, auth_schema_path)

        logger.info("✅ Database initialized successfully!")

    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}", exc_info=True)
        conn.rollback()
        sys.exit(1)

    finally:
        DatabaseConnection.return_connection(conn)
        DatabaseConnection.close_all_connections()


if __name__ == "__main__":
    main()
