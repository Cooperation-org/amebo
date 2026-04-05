"""
Read-only connection to abra's pgvector database.

Abra stores structured knowledge (bindings, content, hot_tags) in a separate
database. Amebo reads from it for binding enrichment in the QA pipeline.

Configure via ABRA_DATABASE_URL in .env.
"""

import os
import logging
import psycopg2
from psycopg2 import pool
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class AbraConnection:
    """Read-only connection pool to abra's database."""

    _pool = None

    @classmethod
    def initialize_pool(cls, minconn=1, maxconn=5):
        if cls._pool is not None:
            return

        abra_url = os.getenv('ABRA_DATABASE_URL')
        if not abra_url:
            logger.info("ABRA_DATABASE_URL not set — abra knowledge not available")
            return

        try:
            cls._pool = psycopg2.pool.SimpleConnectionPool(minconn, maxconn, abra_url)
            logger.info("Abra database connection pool initialized")
        except Exception as e:
            logger.warning(f"Could not connect to abra database: {e}")
            cls._pool = None

    @classmethod
    def get_connection(cls):
        if cls._pool is None:
            cls.initialize_pool()
        if cls._pool is None:
            return None
        return cls._pool.getconn()

    @classmethod
    def return_connection(cls, conn):
        if cls._pool and conn:
            cls._pool.putconn(conn)

    @classmethod
    def is_available(cls):
        if cls._pool is None:
            cls.initialize_pool()
        return cls._pool is not None
