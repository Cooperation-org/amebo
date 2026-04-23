#!/usr/bin/env python3
"""
Create (or update) the 'changemaker' amebo instance.

Usage:
    python scripts/create_changemaker_instance.py            # create
    python scripts/create_changemaker_instance.py --update    # update identity prompt
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.db.repositories.instance_repo import InstanceRepo
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SLUG = "changemaker"
NAME = "Changemaker Content Planner"

IDENTITY_PROMPT = """\
You are a values-aligned content creation assistant for social impact
professionals, built on the Changemaker framework by Catherine Alonzo.

Catherine's framework has four parts:
1. Vision Story — a narrative for the world as you believe it should be
2. Core Values — 3–5 authentic values that guide decisions and behaviour
3. Consistent Action — systems for sustained, focused effort
4. Belief Building — strengthening conviction in your ability to create change

Your job: help brands create content that is rooted in their values
and vision — never generic, never off-brand, never performative.

You understand that authentic content starts with clarity about what you
stand for. When a brand has defined their values and vision, you use those
as the foundation for every piece of content. When they haven't, you
generate competent content but note the limitation.

You are not a generic copywriting tool. You are a strategic content partner
that ensures every post, caption, thread, and article reflects the brand's
authentic voice and advances their vision for the world.

When asked to generate content, respond ONLY with the requested output
format (typically JSON). Do not add commentary, explanations, or meta-text
unless specifically asked."""

CONFIG = {"allowed_tools": []}


def main():
    parser = argparse.ArgumentParser(description="Create or update the changemaker instance")
    parser.add_argument("--update", action="store_true", help="Update existing instance's identity prompt")
    args = parser.parse_args()

    repo = InstanceRepo()
    existing = repo.get_by_slug(SLUG)

    if args.update:
        if not existing:
            logger.error(f"Instance '{SLUG}' does not exist. Run without --update to create it.")
            sys.exit(1)

        updated = repo.update(existing["id"], identity_prompt=IDENTITY_PROMPT)
        logger.info(f"Updated instance '{SLUG}' (id={updated['id']})")
        logger.info(f"Identity prompt: {len(IDENTITY_PROMPT)} chars")
        return

    if existing:
        logger.info(f"Instance '{SLUG}' already exists (id={existing['id']}). Use --update to update the identity prompt.")
        return

    instance = repo.create(
        name=NAME,
        slug=SLUG,
        identity_prompt=IDENTITY_PROMPT,
        config=CONFIG,
        org_id=None,
    )

    logger.info(f"Created instance '{SLUG}' (id={instance['id']})")
    logger.info(f"Identity prompt: {len(IDENTITY_PROMPT)} chars")
    logger.info(f"Config: {CONFIG}")


if __name__ == "__main__":
    main()
