#!/usr/bin/env python3
"""Show or reset which LLM provider amebo is using.

The wanted provider is AMEBO_LLM_PROVIDER in .env. When it fails or spends a
goal's cost budget, amebo drops to the cheaper fallback for AMEBO_LLM_TRIP_HOURS
(default 24) and records it in the DB. This is how a human sees that and undoes
it early.

    python scripts/llm_provider.py            # what is in use, and why
    python scripts/llm_provider.py reset      # back on the wanted provider now
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from src.services.llm_client import clear_trip, provider_status  # noqa: E402


def show() -> None:
    st = provider_status()
    print(f"in use:  {st['in_use']} / {st['model']}")
    trip = st["trip"]
    if not trip:
        print(f"wanted:  {st['configured']} (no trip)")
        return
    print(f"wanted:  {st['configured']} — TRIPPED until {trip['until']}")
    print(f"reason:  {trip['reason']}")
    print("reset:   python scripts/llm_provider.py reset")


def main() -> int:
    arg = (sys.argv[1] if len(sys.argv) > 1 else "status").lower()
    if arg in ("status", "-h", "--help", "help"):
        if arg != "status":
            print(__doc__)
            return 0
        show()
        return 0
    if arg == "reset":
        print("trip cleared" if clear_trip() else "no trip to clear")
        show()
        return 0
    print(f"unknown command {arg!r} — use status or reset", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
