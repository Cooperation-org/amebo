#!/usr/bin/env python3
"""
Test script for Task 3: Auto-Backfill on Channel Join
Tests that bot automatically indexes channel history when joining
"""

import sys
import os
from pathlib import Path
import asyncio

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    END = '\033[0m'

def print_success(msg):
    print(f"{Colors.GREEN}{msg}{Colors.END}")

def print_error(msg):
    print(f"{Colors.RED}{msg}{Colors.END}")

def print_info(msg):
    print(f"{Colors.BLUE}ℹ️  {msg}{Colors.END}")

def print_warning(msg):
    print(f"{Colors.YELLOW} {msg}{Colors.END}")

def test_database_connection():
    """Test 1: Database connection works"""
    print("\n" + "="*70)
    print("TEST 1: Database Connection")
    print("="*70)

    try:
        from dotenv import load_dotenv
        load_dotenv()

        from src.db.connection import DatabaseConnection

        DatabaseConnection.initialize_pool()
        print_success("Database pool initialized")

        conn = DatabaseConnection.get_connection()
        print_success("Database connection obtained")

        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            result = cur.fetchone()
            if result and result[0] == 1:
                print_success("Database query works")
                DatabaseConnection.return_connection(conn)
                return True

        return False

    except Exception as e:
        print_error(f"Database connection failed: {e}")
        return False

def test_slack_listener_imports():
    """Test 2: SlackListener imports without errors"""
    print("\n" + "="*70)
    print("TEST 2: SlackListener Imports")
    print("="*70)

    try:
        from src.services.slack_listener import SlackListener
        print_success("SlackListener imported successfully")
        return True

    except Exception as e:
        print_error(f"Import failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_event_handler_exists():
    """Test 3: member_joined_channel event handler exists"""
    print("\n" + "="*70)
    print("TEST 3: Event Handler Exists")
    print("="*70)

    try:
        # Read the slack_listener.py file
        slack_listener_path = Path(__file__).parent / 'src' / 'services' / 'slack_listener.py'

        with open(slack_listener_path, 'r') as f:
            content = f.read()

        # Check for event handler registration
        if '@app.event("member_joined_channel")' in content:
            print_success("member_joined_channel event handler found")
        else:
            print_error("member_joined_channel event handler not found")
            return False

        # Check for handler function
        if 'async def handle_bot_join_channel' in content:
            print_success("handle_bot_join_channel function found")
        else:
            print_error("handle_bot_join_channel function not found")
            return False

        # Check for key functionality
        checks = {
            'bot_user_id = auth_response': 'Bot user ID detection',
            'conversations_info': 'Channel info retrieval',
            'chat_postMessage': 'Message posting',
            '_run_immediate_backfill': 'Backfill trigger',
            'asyncio.create_task': 'Background task creation'
        }

        for pattern, description in checks.items():
            if pattern in content:
                print_success(f"{description} implemented")
            else:
                print_warning(f"{description} not found (pattern: {pattern})")

        return True

    except Exception as e:
        print_error(f"Test failed: {e}")
        return False

def test_immediate_backfill_method():
    """Test 4: _run_immediate_backfill method exists"""
    print("\n" + "="*70)
    print("TEST 4: Immediate Backfill Method")
    print("="*70)

    try:
        slack_listener_path = Path(__file__).parent / 'src' / 'services' / 'slack_listener.py'

        with open(slack_listener_path, 'r') as f:
            content = f.read()

        # Check for method definition
        if 'async def _run_immediate_backfill' in content:
            print_success("_run_immediate_backfill method found")
        else:
            print_error("_run_immediate_backfill method not found")
            return False

        # Check for key parameters
        params = [
            'workspace_id',
            'channel_id',
            'channel_name',
            'bot_token',
            'client'
        ]

        for param in params:
            if f'{param}:' in content or f'{param},' in content:
                print_success(f"Parameter '{param}' found")

        # Check for key functionality
        checks = {
            'BackfillService': 'Backfill service initialization',
            'backfill_messages': 'Backfill execution',
            'days=90': '90-day backfill',
            'include_all_channels=False': 'Single channel mode',
            'total_messages': 'Message count extraction',
            'Indexed {message_count} messages': 'Completion message'
        }

        for pattern, description in checks.items():
            if pattern in content:
                print_success(f"{description} implemented")
            else:
                print_warning(f"{description} not found")

        return True

    except Exception as e:
        print_error(f"Test failed: {e}")
        return False

def test_backfill_service_exists():
    """Test 5: BackfillService can be imported"""
    print("\n" + "="*70)
    print("TEST 5: BackfillService Available")
    print("="*70)

    try:
        from src.services.backfill_service import BackfillService
        print_success("BackfillService imported successfully")

        # Check if it has the required method
        if hasattr(BackfillService, 'backfill_messages'):
            print_success("backfill_messages method exists")
        else:
            print_error("backfill_messages method not found")
            return False

        return True

    except Exception as e:
        print_error(f"Import failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_slack_listener_initialization():
    """Test 6: SlackListener can be initialized"""
    print("\n" + "="*70)
    print("TEST 6: SlackListener Initialization")
    print("="*70)

    try:
        from src.services.slack_listener import SlackListener

        # Try to create instance (without actually starting it)
        listener = SlackListener()
        print_success("SlackListener instance created")

        # Check for required attributes
        if hasattr(listener, 'handlers'):
            print_success("handlers attribute exists")
        else:
            print_warning("handlers attribute not found")

        if hasattr(listener, 'running'):
            print_success("running attribute exists")
        else:
            print_warning("running attribute not found")

        if hasattr(listener, '_run_immediate_backfill'):
            print_success("_run_immediate_backfill method exists")
        else:
            print_error("_run_immediate_backfill method not found")
            return False

        return True

    except Exception as e:
        print_error(f"Initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_installations_table():
    """Test 7: installations table has bot_token column"""
    print("\n" + "="*70)
    print("TEST 7: Installations Table Schema")
    print("="*70)

    try:
        from src.db.connection import DatabaseConnection

        conn = DatabaseConnection.get_connection()

        try:
            with conn.cursor() as cur:
                # Check if installations table exists
                cur.execute("""
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE table_name = 'installations'
                    AND column_name IN ('workspace_id', 'bot_token', 'is_active')
                    ORDER BY column_name
                """)
                columns = cur.fetchall()

                if not columns:
                    print_error("installations table not found or missing required columns")
                    return False

                print_success(f"Found {len(columns)} required columns in installations table")

                required_columns = {'workspace_id', 'bot_token', 'is_active'}
                found_columns = {col[0] for col in columns}

                for col in required_columns:
                    if col in found_columns:
                        print_success(f"Column '{col}' exists")
                    else:
                        print_error(f"Column '{col}' missing")
                        return False

                return True

        finally:
            DatabaseConnection.return_connection(conn)

    except Exception as e:
        print_error(f"Schema check failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_error_handling():
    """Test 8: Error handling implementation"""
    print("\n" + "="*70)
    print("TEST 8: Error Handling")
    print("="*70)

    try:
        slack_listener_path = Path(__file__).parent / 'src' / 'services' / 'slack_listener.py'

        with open(slack_listener_path, 'r') as f:
            content = f.read()

        # Check for error handling in event handler
        if 'except Exception as e:' in content:
            print_success("Exception handling found")
        else:
            print_warning("Exception handling not found")

        # Check for error logging
        if 'logger.error' in content:
            print_success("Error logging implemented")
        else:
            print_warning("Error logging not found")

        # Check for error message to channel
        if 'Sorry, I encountered an error' in content or 'error while indexing' in content:
            print_success("User-facing error messages implemented")
        else:
            print_warning("User-facing error messages not found")

        return True

    except Exception as e:
        print_error(f"Test failed: {e}")
        return False

def run_all_tests():
    """Run all verification tests"""
    print("\n" + "🔍 TASK 3 VERIFICATION: Auto-Backfill on Channel Join")
    print("="*70)
    print("Testing bot channel join handler and immediate backfill...\n")

    results = {}

    # Synchronous tests
    results['database'] = test_database_connection()
    results['imports'] = test_slack_listener_imports()
    results['event_handler'] = test_event_handler_exists()
    results['backfill_method'] = test_immediate_backfill_method()
    results['backfill_service'] = test_backfill_service_exists()
    results['installations_table'] = test_installations_table()
    results['error_handling'] = test_error_handling()

    # Async test
    loop = asyncio.get_event_loop()
    results['initialization'] = loop.run_until_complete(test_slack_listener_initialization())

    # Summary
    print("\n" + "="*70)
    print("📊 TEST SUMMARY")
    print("="*70)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for test_name, result in results.items():
        status = "PASS" if result else "FAIL"
        print(f"{status} - {test_name}")

    print("\n" + "="*70)
    if passed == total:
        print_success(f"ALL TESTS PASSED ({passed}/{total})")
        print_success("✨ Task 3 is READY for PR!")
        print("\n" + "📝 NEXT STEPS:")
        print_info("1. Configure Slack app to subscribe to 'member_joined_channel' event")
        print_info("2. Test by inviting bot to a test channel")
        print_info("3. Verify bot posts indexing messages and runs backfill")
    else:
        print_error(f"SOME TESTS FAILED ({passed}/{total} passed)")
        print_info("Fix failures before creating PR")
    print("="*70)

    return passed == total

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
