#!/usr/bin/env python3
"""
Database initialization script.
Creates all required tables from schema.sql
"""

import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.db.connection import DatabaseConnection
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def init_database():
    """Initialize database with schema"""
    print("=" * 70)
    print("DATABASE INITIALIZATION")
    print("=" * 70)
    print()

    # Read schema file
    schema_path = Path(__file__).parent / "src" / "db" / "schema.sql"

    if not schema_path.exists():
        print(f"❌ Schema file not found: {schema_path}")
        sys.exit(1)

    print(f"📄 Reading schema from: {schema_path}")
    with open(schema_path, 'r') as f:
        schema_sql = f.read()

    # Initialize connection pool
    DatabaseConnection.initialize_pool()
    conn = DatabaseConnection.get_connection()

    try:
        print("🔨 Creating database tables...")

        # Execute schema
        with conn.cursor() as cur:
            cur.execute(schema_sql)
            conn.commit()

        print("✅ Database tables created successfully!")
        print()

        # Verify tables
        print("📋 Verifying tables...")
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name
            """)
            tables = cur.fetchall()

            print(f"   Found {len(tables)} tables:")
            for table in tables:
                print(f"   ✓ {table[0]}")

        print()
        print("=" * 70)
        print("✅ DATABASE INITIALIZATION COMPLETE")
        print("=" * 70)

    except Exception as e:
        print(f"❌ Error initializing database: {e}")
        conn.rollback()
        sys.exit(1)
    finally:
        DatabaseConnection.return_connection(conn)
        DatabaseConnection.close_all_connections()


if __name__ == "__main__":
    init_database()
