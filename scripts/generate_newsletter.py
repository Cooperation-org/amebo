#!/usr/bin/env python3
"""
Newsletter Generation CLI - Generate periodic summaries of Slack activity.

Usage:
    python scripts/generate_newsletter.py --days 7
    python scripts/generate_newsletter.py --days 30 --format markdown --output newsletter.md
"""

import sys
import os
import argparse
from datetime import datetime

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.services.newsletter_service import NewsletterService
from src.db.connection import DatabaseConnection


def generate_and_display_newsletter(
    workspace_id: str,
    days_back: int,
    format_type: str = 'text',
    output_file: str = None
):
    """
    Generate and display/save newsletter.

    Args:
        workspace_id: Workspace ID
        days_back: Number of days to look back
        format_type: Output format ('text' or 'markdown')
        output_file: Optional file to save to
    """
    print(f"Generating newsletter for last {days_back} days...\n")

    # Initialize service
    newsletter_service = NewsletterService(workspace_id=workspace_id)

    # Generate newsletter
    newsletter = newsletter_service.generate_newsletter(days_back=days_back)

    # Format newsletter
    if format_type == 'markdown':
        output = newsletter_service.format_newsletter_markdown(newsletter)
    else:
        output = newsletter_service.format_newsletter_text(newsletter)

    # Display or save
    if output_file:
        with open(output_file, 'w') as f:
            f.write(output)
        print(f"✅ Newsletter saved to: {output_file}")
        print(f"\nPreview (first 500 characters):")
        print(output[:500])
        print("...")
    else:
        print(output)


def main():
    parser = argparse.ArgumentParser(
        description='Generate newsletter from Slack workspace activity'
    )
    parser.add_argument(
        '--workspace',
        type=str,
        default='W_DEFAULT',
        help='Workspace ID (default: W_DEFAULT)'
    )
    parser.add_argument(
        '--days',
        type=int,
        default=7,
        help='Number of days to look back (default: 7)'
    )
    parser.add_argument(
        '--format',
        type=str,
        choices=['text', 'markdown'],
        default='text',
        help='Output format (default: text)'
    )
    parser.add_argument(
        '--output',
        type=str,
        help='Output file path (if not specified, prints to console)'
    )

    args = parser.parse_args()

    try:
        generate_and_display_newsletter(
            workspace_id=args.workspace,
            days_back=args.days,
            format_type=args.format,
            output_file=args.output
        )
    finally:
        DatabaseConnection.close_all_connections()


if __name__ == "__main__":
    main()
