#!/usr/bin/env python3
"""
Test script for Task 4: Conversation Manager
Tests multi-turn conversation context tracking
"""

import sys
import os
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    END = '\033[0m'

def print_success(msg):
    print(f"{Colors.GREEN}✅ {msg}{Colors.END}")

def print_error(msg):
    print(f"{Colors.RED}❌ {msg}{Colors.END}")

def print_info(msg):
    print(f"{Colors.BLUE}ℹ️  {msg}{Colors.END}")

def print_warning(msg):
    print(f"{Colors.YELLOW}⚠️  {msg}{Colors.END}")

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

def test_conversation_history_table():
    """Test 2: conversation_history table exists with correct schema"""
    print("\n" + "="*70)
    print("TEST 2: Conversation History Table Schema")
    print("="*70)

    try:
        from src.db.connection import DatabaseConnection

        conn = DatabaseConnection.get_connection()

        try:
            with conn.cursor() as cur:
                # Check if table exists
                cur.execute("""
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE table_name = 'conversation_history'
                    ORDER BY ordinal_position
                """)
                columns = cur.fetchall()

                if not columns:
                    print_error("conversation_history table not found")
                    print_info("Run migration: python migrate_slack_padi.py")
                    return False

                print_success(f"Table exists with {len(columns)} columns")

                # Check required columns
                required_columns = {
                    'conversation_id', 'workspace_id', 'thread_ts',
                    'channel_id', 'role', 'content', 'created_at'
                }
                found_columns = {col[0] for col in columns}

                for col in required_columns:
                    if col in found_columns:
                        print_success(f"Column '{col}' exists")
                    else:
                        print_error(f"Column '{col}' missing")
                        return False

                # Check index exists
                cur.execute("""
                    SELECT indexname
                    FROM pg_indexes
                    WHERE tablename = 'conversation_history'
                    AND indexname = 'idx_conversation_thread'
                """)
                index = cur.fetchone()

                if index:
                    print_success("Index 'idx_conversation_thread' exists")
                else:
                    print_warning("Index 'idx_conversation_thread' not found (optional)")

                return True

        finally:
            DatabaseConnection.return_connection(conn)

    except Exception as e:
        print_error(f"Schema check failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_conversation_manager_import():
    """Test 3: ConversationManager imports successfully"""
    print("\n" + "="*70)
    print("TEST 3: ConversationManager Import")
    print("="*70)

    try:
        from src.services.conversation_manager import ConversationManager
        print_success("ConversationManager imported successfully")

        # Check class attributes
        print_info("Checking class methods...")
        required_methods = [
            'add_to_history',
            'get_thread_history',
            'build_context_prompt',
            'clear_thread_history',
            'get_recent_conversations'
        ]

        for method in required_methods:
            if hasattr(ConversationManager, method):
                print_success(f"Method '{method}' exists")
            else:
                print_error(f"Method '{method}' missing")
                return False

        return True

    except Exception as e:
        print_error(f"Import failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_add_to_history():
    """Test 4: Add messages to conversation history"""
    print("\n" + "="*70)
    print("TEST 4: Add Messages to History")
    print("="*70)

    try:
        from src.services.conversation_manager import ConversationManager

        manager = ConversationManager(workspace_id="TEST_WORKSPACE")
        print_success("ConversationManager initialized")

        # Test thread ID (realistic Slack format: 10 digits . 6 digits = 17 chars)
        thread_ts = "1234567890.123456"
        channel_id = "C123456"

        # Add user message
        print_info("Adding user message...")
        result = manager.add_to_history(
            thread_ts=thread_ts,
            channel_id=channel_id,
            role="user",
            content="What is the status of the project?"
        )

        if result:
            print_success("User message stored")
        else:
            print_error("Failed to store user message")
            return False

        # Add assistant message
        print_info("Adding assistant message...")
        result = manager.add_to_history(
            thread_ts=thread_ts,
            channel_id=channel_id,
            role="assistant",
            content="The project is on track. We completed phase 1 last week."
        )

        if result:
            print_success("Assistant message stored")
        else:
            print_error("Failed to store assistant message")
            return False

        # Test invalid role
        print_info("Testing invalid role handling...")
        result = manager.add_to_history(
            thread_ts=thread_ts,
            channel_id=channel_id,
            role="invalid_role",
            content="This should fail"
        )

        if not result:
            print_success("Invalid role rejected correctly")
        else:
            print_error("Invalid role was accepted (should have failed)")
            return False

        return True

    except Exception as e:
        print_error(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_get_thread_history():
    """Test 5: Retrieve conversation history"""
    print("\n" + "="*70)
    print("TEST 5: Retrieve Thread History")
    print("="*70)

    try:
        from src.services.conversation_manager import ConversationManager

        manager = ConversationManager(workspace_id="TEST_WORKSPACE")
        thread_ts = "1234567890.123456"

        print_info("Retrieving thread history...")
        history = manager.get_thread_history(thread_ts=thread_ts)

        if not history:
            print_error("No history returned")
            return False

        print_success(f"Retrieved {len(history)} messages")

        # Verify structure
        for i, msg in enumerate(history):
            if 'role' not in msg or 'content' not in msg:
                print_error(f"Message {i} missing required fields")
                return False

            role = msg['role']
            content = msg['content'][:50]  # First 50 chars
            print_info(f"  [{role}] {content}...")

        # Verify chronological order
        if len(history) >= 2:
            if history[0]['role'] == 'user' and history[1]['role'] == 'assistant':
                print_success("Messages in correct chronological order")
            else:
                print_warning("Message order unexpected")

        return True

    except Exception as e:
        print_error(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_build_context_prompt():
    """Test 6: Build context-aware prompt"""
    print("\n" + "="*70)
    print("TEST 6: Build Context Prompt")
    print("="*70)

    try:
        from src.services.conversation_manager import ConversationManager

        manager = ConversationManager(workspace_id="TEST_WORKSPACE")
        thread_ts = "1234567890.123456"
        new_question = "When is phase 2 starting?"

        print_info("Building context prompt...")
        prompt = manager.build_context_prompt(
            thread_ts=thread_ts,
            new_question=new_question
        )

        if not prompt:
            print_error("Empty prompt returned")
            return False

        print_success("Context prompt generated")
        print_info(f"Prompt length: {len(prompt)} characters")

        # Verify prompt includes previous context
        if "Previous conversation:" in prompt:
            print_success("Prompt includes previous conversation")
        else:
            print_warning("Prompt doesn't include previous conversation marker")

        # Verify prompt includes new question
        if new_question in prompt:
            print_success("Prompt includes new question")
        else:
            print_error("Prompt missing new question")
            return False

        # Display sample (first 300 chars)
        print_info("Sample prompt:")
        print(f"  {prompt[:300]}...")

        return True

    except Exception as e:
        print_error(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_multi_turn_conversation():
    """Test 7: Multi-turn conversation flow"""
    print("\n" + "="*70)
    print("TEST 7: Multi-Turn Conversation")
    print("="*70)

    try:
        from src.services.conversation_manager import ConversationManager

        manager = ConversationManager(workspace_id="TEST_WORKSPACE")
        thread_ts = "9876543210.654321"  # Different thread for multi-turn test
        channel_id = "C999999"

        # Clear any existing history for this thread
        manager.clear_thread_history(thread_ts)

        print_info("Simulating 3-turn conversation...")

        # Turn 1
        manager.add_to_history(thread_ts, channel_id, "user", "What is our budget?")
        manager.add_to_history(thread_ts, channel_id, "assistant", "$100,000")

        # Turn 2
        manager.add_to_history(thread_ts, channel_id, "user", "How much have we spent?")
        manager.add_to_history(thread_ts, channel_id, "assistant", "$45,000 so far")

        # Turn 3
        manager.add_to_history(thread_ts, channel_id, "user", "What's remaining?")
        manager.add_to_history(thread_ts, channel_id, "assistant", "$55,000 remaining")

        print_success("Added 6 messages (3 turns)")

        # Retrieve and verify
        history = manager.get_thread_history(thread_ts)

        if len(history) != 6:
            print_error(f"Expected 6 messages, got {len(history)}")
            return False

        print_success(f"Retrieved all {len(history)} messages")

        # Build context with all history
        prompt = manager.build_context_prompt(thread_ts, "Can we increase it?")

        # Verify all turns are in context
        keywords = ["budget", "spent", "remaining"]
        for kw in keywords:
            if kw.lower() in prompt.lower():
                print_success(f"Context includes '{kw}'")
            else:
                print_warning(f"Context missing '{kw}'")

        return True

    except Exception as e:
        print_error(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_clear_history():
    """Test 8: Clear conversation history"""
    print("\n" + "="*70)
    print("TEST 8: Clear Conversation History")
    print("="*70)

    try:
        from src.services.conversation_manager import ConversationManager

        manager = ConversationManager(workspace_id="TEST_WORKSPACE")
        thread_ts = "1234567890.123456"

        # Verify history exists
        print_info("Checking history before clear...")
        history_before = manager.get_thread_history(thread_ts)
        print_info(f"Found {len(history_before)} messages")

        # Clear history
        print_info("Clearing history...")
        result = manager.clear_thread_history(thread_ts)

        if not result:
            print_error("Clear operation failed")
            return False

        print_success("History cleared")

        # Verify history is empty
        history_after = manager.get_thread_history(thread_ts)

        if len(history_after) == 0:
            print_success("History confirmed empty")
            return True
        else:
            print_error(f"History not empty ({len(history_after)} messages remain)")
            return False

    except Exception as e:
        print_error(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_get_recent_conversations():
    """Test 9: Get recent conversations"""
    print("\n" + "="*70)
    print("TEST 9: Get Recent Conversations")
    print("="*70)

    try:
        from src.services.conversation_manager import ConversationManager

        manager = ConversationManager(workspace_id="TEST_WORKSPACE")

        print_info("Getting recent conversations...")
        conversations = manager.get_recent_conversations(limit=5)

        print_success(f"Retrieved {len(conversations)} recent conversations")

        for conv in conversations:
            if 'thread_ts' not in conv or 'channel_id' not in conv:
                print_error("Conversation missing required fields")
                return False

            print_info(f"  Thread: {conv['thread_ts']} in {conv['channel_id']}")

        return True

    except Exception as e:
        print_error(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def run_all_tests():
    """Run all verification tests"""
    print("\n" + "🔍 TASK 4 VERIFICATION: Conversation Manager")
    print("="*70)
    print("Testing multi-turn conversation context tracking...\n")

    results = {}

    # Run tests
    results['database'] = test_database_connection()
    results['table_schema'] = test_conversation_history_table()
    results['import'] = test_conversation_manager_import()
    results['add_history'] = test_add_to_history()
    results['get_history'] = test_get_thread_history()
    results['build_prompt'] = test_build_context_prompt()
    results['multi_turn'] = test_multi_turn_conversation()
    results['clear_history'] = test_clear_history()
    results['recent_conversations'] = test_get_recent_conversations()

    # Summary
    print("\n" + "="*70)
    print("📊 TEST SUMMARY")
    print("="*70)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {test_name}")

    print("\n" + "="*70)
    if passed == total:
        print_success(f"ALL TESTS PASSED ({passed}/{total})")
        print_success("✨ Task 4 is READY for PR!")
        print("\n" + "📝 NEXT STEPS:")
        print_info("1. Integrate ConversationManager with Q&A service (Task 12)")
        print_info("2. Test multi-turn conversations in real Slack channels")
    else:
        print_error(f"SOME TESTS FAILED ({passed}/{total} passed)")
        print_info("Fix failures before creating PR")
    print("="*70)

    return passed == total

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
