#!/usr/bin/env python3
"""
Interactive Q&A CLI - Ask questions about your Slack workspace.

Usage:
    python scripts/ask_question.py "How do I deploy to production?"
    python scripts/ask_question.py --interactive
"""

import sys
import os
import argparse

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.services.qa_service import QAService
from src.db.connection import DatabaseConnection


def ask_question(qa_service: QAService, question: str, verbose: bool = False):
    """
    Ask a question and display the answer.

    Args:
        qa_service: QAService instance
        question: Question to ask
        verbose: Show detailed sources
    """
    print(f"\n{'='*70}")
    print(f"Question: {question}")
    print('='*70)

    # Get answer
    result = qa_service.answer_question(
        question=question,
        n_context_messages=10
    )

    # Display answer
    print(f"\nAnswer (confidence: {result['confidence']}):")
    print(f"{result['answer']}\n")

    # Display sources
    if verbose and result['sources']:
        print(f"Sources ({result['context_used']} messages analyzed):")
        print("-" * 70)
        for i, source in enumerate(result['sources'], 1):
            print(f"\n{i}. #{source['channel']} - {source['user']}")
            print(f"   {source['text']}")
        print("-" * 70)
    elif result['sources']:
        print(f"📚 Based on {result['context_used']} messages from your Slack history")
        print(f"   Channels: {', '.join(set('#' + s['channel'] for s in result['sources']))}")


def interactive_mode(qa_service: QAService):
    """
    Interactive Q&A session.

    Args:
        qa_service: QAService instance
    """
    print("\n" + "="*70)
    print("🤖 Slack Helper Bot - Interactive Q&A")
    print("="*70)
    print("\nAsk questions about your Slack workspace history!")
    print("Type 'exit' or 'quit' to stop\n")

    while True:
        try:
            question = input("❓ Your question: ").strip()

            if not question:
                continue

            if question.lower() in ['exit', 'quit', 'q']:
                print("\n👋 Goodbye!")
                break

            ask_question(qa_service, question, verbose=False)

        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
            break
        except EOFError:
            break


def main():
    parser = argparse.ArgumentParser(
        description='Ask questions about your Slack workspace'
    )
    parser.add_argument(
        'question',
        nargs='?',
        help='Question to ask (if not in interactive mode)'
    )
    parser.add_argument(
        '--workspace',
        type=str,
        default='W_DEFAULT',
        help='Workspace ID (default: W_DEFAULT)'
    )
    parser.add_argument(
        '-i', '--interactive',
        action='store_true',
        help='Start interactive mode'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Show detailed sources'
    )

    args = parser.parse_args()

    # Initialize Q&A service
    qa_service = QAService(workspace_id=args.workspace)

    try:
        if args.interactive:
            # Interactive mode
            interactive_mode(qa_service)
        elif args.question:
            # Single question mode
            ask_question(qa_service, args.question, verbose=args.verbose)
        else:
            # No question provided
            parser.print_help()
            print("\nExample usage:")
            print('  python scripts/ask_question.py "What are people working on?"')
            print('  python scripts/ask_question.py --interactive')

    finally:
        DatabaseConnection.close_all_connections()


if __name__ == "__main__":
    main()
