#!/usr/bin/env python3
"""
Quick Q&A Test Script
Tests the Q&A API with your existing W_DEFAULT workspace
"""

import sys
import os
import requests
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

API_BASE_URL = "http://localhost:8000"


def create_test_user():
    """Create test user and organization"""
    print("📝 Creating test user...")

    response = requests.post(
        f"{API_BASE_URL}/api/auth/signup",
        json={
            "email": "test@example.com",
            "password": "TestPass123",
            "full_name": "Test User",
            "org_name": "Test Organization"
        }
    )

    if response.status_code == 201:
        data = response.json()
        print(f"✅ User created successfully!")
        return data['access_token']
    elif response.status_code == 400 and "already registered" in response.json().get('detail', ''):
        # User exists, try login
        print("User exists, logging in...")
        return login_user()
    else:
        print(f"❌ Failed to create user: {response.text}")
        return None


def login_user():
    """Login existing user"""
    response = requests.post(
        f"{API_BASE_URL}/api/auth/login",
        json={
            "email": "test@example.com",
            "password": "TestPass123"
        }
    )

    if response.status_code == 200:
        data = response.json()
        print("✅ Logged in successfully!")
        return data['access_token']
    else:
        print(f"❌ Login failed: {response.text}")
        return None


def link_workspace_to_org(token):
    """Link W_DEFAULT workspace to the organization"""
    from src.db.connection import DatabaseConnection

    print("\n🔗 Linking W_DEFAULT workspace to organization...")

    # Get user info from API instead of decoding token
    response = requests.get(
        f"{API_BASE_URL}/api/auth/me",
        headers={"Authorization": f"Bearer {token}"}
    )

    if response.status_code != 200:
        print(f"❌ Failed to get user info: {response.text}")
        return

    user_data = response.json()
    org_id = user_data['org_id']

    DatabaseConnection.initialize_pool()
    conn = DatabaseConnection.get_connection()

    try:
        with conn.cursor() as cur:
            cur.execute('''
                INSERT INTO org_workspaces (org_id, workspace_id, display_name, added_at)
                VALUES (%s, 'W_DEFAULT', 'Default Workspace', NOW())
                ON CONFLICT (org_id, workspace_id) DO NOTHING
            ''', (org_id,))

            conn.commit()
            print("✅ W_DEFAULT workspace linked!")

    finally:
        DatabaseConnection.return_connection(conn)
        DatabaseConnection.close_all_connections()


def ask_question(token, question):
    """Ask a question via Q&A API"""
    print(f"\n❓ Question: {question}")
    print("🤔 Thinking...")

    response = requests.post(
        f"{API_BASE_URL}/api/qa/ask",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "question": question,
            "workspace_id": "W_DEFAULT",
            "include_slack": True,
            "include_documents": False,
            "max_sources": 10
        }
    )

    if response.status_code == 200:
        data = response.json()

        print("\n" + "=" * 70)
        print("📖 ANSWER:")
        print("=" * 70)
        print(data['answer'])
        print("\n" + "=" * 70)
        print(f"⏱️  Processing time: {data['processing_time_ms']:.0f}ms")
        print(f"📊 Confidence: {data['confidence']}")
        print(f"📚 Sources: {len(data['sources'])} messages")

        if data['sources']:
            print("\nTop Sources:")
            for i, source in enumerate(data['sources'][:3], 1):
                channel = source['metadata'].get('channel_name', 'unknown')
                user = source['metadata'].get('user_name', 'unknown')
                text_preview = source['text'][:80] + "..." if len(source['text']) > 80 else source['text']
                print(f"  {i}. #{channel} - {user}: {text_preview}")

        print("=" * 70)

    else:
        print(f"❌ Error: {response.text}")


def main():
    print("=" * 70)
    print("SLACK HELPER BOT - Q&A TEST")
    print("=" * 70)

    # Check if API is running
    try:
        requests.get(f"{API_BASE_URL}/health", timeout=2)
    except requests.exceptions.ConnectionError:
        print("\n❌ Error: FastAPI server is not running!")
        print("\nPlease start the server first:")
        print("  PYTHONPATH=. uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000")
        sys.exit(1)

    # Create/login user
    token = create_test_user()
    if not token:
        sys.exit(1)

    # Link workspace
    link_workspace_to_org(token)

    # Test questions
    questions = [
        "What hackathon projects are people discussing?",
        "What are the main topics discussed this week?",
        "Who is working on AI projects?",
    ]

    print("\n" + "=" * 70)
    print("Testing Q&A with sample questions...")
    print("=" * 70)

    for question in questions:
        ask_question(token, question)
        print()

    # Interactive mode
    print("\n" + "=" * 70)
    print("🎮 INTERACTIVE MODE")
    print("=" * 70)
    print("Type your questions (or 'quit' to exit):\n")

    while True:
        try:
            question = input("❓ Your question: ").strip()

            if not question:
                continue

            if question.lower() in ['quit', 'exit', 'q']:
                print("\n👋 Goodbye!")
                break

            ask_question(token, question)
            print()

        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
            break
        except Exception as e:
            print(f"\n❌ Error: {e}")


if __name__ == "__main__":
    main()
