"""
Database connection module for Slack Helper Bot.
Handles PostgreSQL connections and provides a connection pool.
"""

import os
import psycopg2
from psycopg2 import pool, extras
from dotenv import load_dotenv
import logging

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)


class DatabaseConnection:
    """
    Manages PostgreSQL database connections with connection pooling.
    """

    _connection_pool = None

    @classmethod
    def initialize_pool(cls, minconn=2, maxconn=20):
        """
        Initialize the connection pool.

        Args:
            minconn: Minimum number of connections to maintain
            maxconn: Maximum number of connections allowed
        """
        try:
            # Try DATABASE_URL first (Heroku/Cloud style)
            database_url = os.getenv('DATABASE_URL')

            if database_url:
                cls._connection_pool = psycopg2.pool.SimpleConnectionPool(
                    minconn,
                    maxconn,
                    database_url
                )
            else:
                # Fall back to individual components
                cls._connection_pool = psycopg2.pool.SimpleConnectionPool(
                    minconn,
                    maxconn,
                    host=os.getenv('DB_HOST', 'localhost'),
                    port=os.getenv('DB_PORT', '5432'),
                    database=os.getenv('DB_NAME', 'slack_helper'),
                    user=os.getenv('DB_USER', 'user'),
                    password=os.getenv('DB_PASSWORD', '')
                )

            logger.info("Database connection pool initialized")

        except Exception as e:
            logger.error(f"Failed to initialize database pool: {e}")
            raise

    @classmethod
    def get_connection(cls):
        """
        Get a connection from the pool.

        Returns:
            psycopg2 connection object
        """
        if cls._connection_pool is None:
            cls.initialize_pool()

        try:
            return cls._connection_pool.getconn()
        except Exception as e:
            logger.error(f"Failed to get connection from pool: {e}")
            raise

    @classmethod
    def return_connection(cls, connection):
        """
        Return a connection to the pool.

        Args:
            connection: psycopg2 connection to return
        """
        if cls._connection_pool:
            cls._connection_pool.putconn(connection)

    @classmethod
    def close_all_connections(cls):
        """
        Close all connections in the pool.
        """
        if cls._connection_pool:
            try:
                cls._connection_pool.closeall()
                cls._connection_pool = None
                logger.info("All database connections closed")
            except Exception as e:
                logger.warning(f"Error closing connection pool: {e}")
                cls._connection_pool = None


def get_db_connection():
    """
    Convenience function to get a database connection.
    Use with context manager for automatic cleanup.

    Example:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM messages LIMIT 1")
    """
    return DatabaseConnection.get_connection()


def execute_query(query, params=None, fetch=True):
    """
    Execute a query and optionally fetch results.

    Args:
        query: SQL query string
        params: Query parameters (tuple or dict)
        fetch: Whether to fetch results (default True)

    Returns:
        Query results if fetch=True, else None
    """
    conn = None
    try:
        conn = DatabaseConnection.get_connection()
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            cur.execute(query, params)

            if fetch:
                results = cur.fetchall()
                return results
            else:
                conn.commit()
                return cur.rowcount

    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Query execution failed: {e}")
        raise
    finally:
        if conn:
            DatabaseConnection.return_connection(conn)


def execute_many(query, params_list):
    """
    Execute a query with multiple parameter sets (bulk insert).

    Args:
        query: SQL query string with placeholders
        params_list: List of parameter tuples

    Returns:
        Number of rows affected
    """
    conn = None
    try:
        conn = DatabaseConnection.get_connection()
        with conn.cursor() as cur:
            extras.execute_batch(cur, query, params_list)
            conn.commit()
            return cur.rowcount

    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Bulk execution failed: {e}")
        raise
    finally:
        if conn:
            DatabaseConnection.return_connection(conn)


def test_connection():
    """
    Test the database connection.

    Returns:
        bool: True if connection successful, False otherwise
    """
    try:
        result = execute_query("SELECT version()")
        if result:
            logger.info(f"Database connection successful: {result[0]['version']}")
            return True
        return False
    except Exception as e:
        logger.error(f"Database connection test failed: {e}")
        return False


if __name__ == "__main__":
    # Test the connection when run directly
    logging.basicConfig(level=logging.INFO)

    print("Testing database connection...")
    if test_connection():
        print("✅ Connection successful!")

        # Test query
        print("\nTesting table count...")
        result = execute_query("""
            SELECT COUNT(*) as table_count
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        """)
        print(f"✅ Found {result[0]['table_count']} tables")

        # List tables
        print("\nListing tables...")
        tables = execute_query("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """)
        for table in tables:
            print(f"  - {table['table_name']}")

    else:
        print("❌ Connection failed!")

    # Clean up
    DatabaseConnection.close_all_connections()
