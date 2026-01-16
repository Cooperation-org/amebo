#!/usr/bin/env python3
"""
Migration script for Slack Padi features
Adds new tables and columns without affecting existing data
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from src.db.connection import DatabaseConnection
from dotenv import load_dotenv

load_dotenv()

def run_migration():
    print("=" * 70)
    print("SLACK PADI MIGRATION")
    print("=" * 70)

    DatabaseConnection.initialize_pool()
    conn = DatabaseConnection.get_connection()

    try:
        with conn.cursor() as cur:
            print("\n📋 Step 1: Updating backfill_schedules table...")

            # Add new columns to backfill_schedules if they don't exist
            cur.execute("""
                ALTER TABLE backfill_schedules
                ADD COLUMN IF NOT EXISTS cron_expression VARCHAR(50) DEFAULT '*/30 * * * *';
            """)

            cur.execute("""
                ALTER TABLE backfill_schedules
                ADD COLUMN IF NOT EXISTS include_all_channels BOOLEAN DEFAULT true;
            """)

            # Update schedule_type default
            cur.execute("""
                ALTER TABLE backfill_schedules
                ALTER COLUMN schedule_type SET DEFAULT 'cron';
            """)

            # Update days_to_backfill default to 90
            cur.execute("""
                ALTER TABLE backfill_schedules
                ALTER COLUMN days_to_backfill SET DEFAULT 90;
            """)

            print("✅ Updated backfill_schedules table")

            print("\n📋 Step 2: Creating indexing_status table...")

            cur.execute("""
                CREATE TABLE IF NOT EXISTS indexing_status (
                    workspace_id VARCHAR(20) NOT NULL,
                    channel_id VARCHAR(20) NOT NULL,
                    last_indexed_ts VARCHAR(20),
                    oldest_indexed_ts VARCHAR(20),
                    total_messages INT DEFAULT 0,
                    last_sync_at TIMESTAMP DEFAULT NOW(),
                    status VARCHAR(20) DEFAULT 'current',
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    PRIMARY KEY (workspace_id, channel_id),
                    FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id) ON DELETE CASCADE
                );
            """)

            # Create indexes if they don't exist
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_indexing_status_workspace
                ON indexing_status(workspace_id);
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_indexing_status_status
                ON indexing_status(status);
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_indexing_status_last_sync
                ON indexing_status(last_sync_at);
            """)

            print("✅ Created indexing_status table")

            print("\n📋 Step 3: Creating conversation_history table...")

            cur.execute("""
                CREATE TABLE IF NOT EXISTS conversation_history (
                    conversation_id SERIAL PRIMARY KEY,
                    workspace_id VARCHAR(20) NOT NULL,
                    thread_ts VARCHAR(20) NOT NULL,
                    channel_id VARCHAR(20) NOT NULL,
                    role VARCHAR(10) NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW(),
                    FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id) ON DELETE CASCADE
                );
            """)

            # Create indexes if they don't exist
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_conversation_thread
                ON conversation_history(workspace_id, thread_ts, created_at);
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_conversation_workspace
                ON conversation_history(workspace_id);
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_conversation_channel
                ON conversation_history(workspace_id, channel_id);
            """)

            print("✅ Created conversation_history table")

            # Commit all changes
            conn.commit()

            print("\n" + "=" * 70)
            print("✅ MIGRATION COMPLETED SUCCESSFULLY")
            print("=" * 70)

            # Verify tables
            print("\n📊 Verifying new tables...")
            cur.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name IN ('indexing_status', 'conversation_history')
                ORDER BY table_name
            """)
            tables = cur.fetchall()
            for table in tables:
                print(f"   ✓ {table[0]}")

            # Check backfill_schedules columns
            print("\n📊 Verifying backfill_schedules columns...")
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'backfill_schedules'
                AND column_name IN ('cron_expression', 'include_all_channels')
                ORDER BY column_name
            """)
            columns = cur.fetchall()
            for col in columns:
                print(f"   ✓ {col[0]}")

    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        conn.rollback()
        import traceback
        traceback.print_exc()
        sys.exit(1)

    finally:
        DatabaseConnection.return_connection(conn)
        DatabaseConnection.close_all_connections()

if __name__ == "__main__":
    run_migration()
