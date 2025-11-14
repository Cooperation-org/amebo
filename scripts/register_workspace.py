#!/usr/bin/env python3
"""
Register existing W_DEFAULT workspace for Slack commands
This adds the workspace to the installations table so the command handler can find it
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.db.connection import DatabaseConnection
from dotenv import load_dotenv

load_dotenv()

def register_workspace():
    """Register W_DEFAULT workspace with tokens from .env"""

    bot_token = os.getenv("SLACK_BOT_TOKEN")
    app_token = os.getenv("SLACK_APP_TOKEN")
    signing_secret = os.getenv("SLACK_SIGNING_SECRET")

    if not bot_token:
        print("❌ SLACK_BOT_TOKEN not found in .env")
        return False

    if not app_token:
        print("❌ SLACK_APP_TOKEN not found in .env")
        print("   You need to enable Socket Mode and generate an app-level token")
        return False

    print("📝 Registering W_DEFAULT workspace...")
    print(f"   Bot token: {bot_token[:20]}...")
    print(f"   App token: {app_token[:20]}...")

    DatabaseConnection.initialize_pool()
    conn = DatabaseConnection.get_connection()

    try:
        with conn.cursor() as cur:
            # Check if workspace exists
            cur.execute("SELECT workspace_id FROM workspaces WHERE workspace_id = %s", ('W_DEFAULT',))
            if not cur.fetchone():
                # Create workspace
                cur.execute("""
                    INSERT INTO workspaces (workspace_id, team_name, is_active)
                    VALUES ('W_DEFAULT', 'Default Workspace', true)
                    ON CONFLICT (workspace_id) DO NOTHING
                """)
                print("✅ Workspace created")

            # Update or create installation
            cur.execute("""
                INSERT INTO installations (workspace_id, bot_token, app_token, signing_secret, is_active)
                VALUES ('W_DEFAULT', %s, %s, %s, true)
                ON CONFLICT (workspace_id)
                DO UPDATE SET
                    bot_token = EXCLUDED.bot_token,
                    app_token = EXCLUDED.app_token,
                    signing_secret = EXCLUDED.signing_secret,
                    is_active = true,
                    last_active = NOW()
            """, (bot_token, app_token, signing_secret))

            conn.commit()
            print("✅ Installation registered successfully!")
            print("")
            print("You can now:")
            print("1. Run: python scripts/start_slack_commands.py")
            print("2. In Slack, type: /ask What are people discussing?")

            return True

    except Exception as e:
        print(f"❌ Error: {e}")
        conn.rollback()
        return False
    finally:
        DatabaseConnection.return_connection(conn)
        DatabaseConnection.close_all_connections()


if __name__ == "__main__":
    print("=" * 70)
    print("REGISTER WORKSPACE FOR SLACK COMMANDS")
    print("=" * 70)
    print("")

    if register_workspace():
        print("")
        print("=" * 70)
        print("✅ SUCCESS!")
        print("=" * 70)
    else:
        print("")
        print("=" * 70)
        print("❌ FAILED - Please check the errors above")
        print("=" * 70)
        sys.exit(1)
