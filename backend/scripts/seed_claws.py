#!/usr/bin/env python3
"""Load the portable claws in backend/seeds/claws/ into this deploy.

Every deploy has its own database, so claws are carried as data in the repo and
loaded here rather than copied between databases. Writes go through
``POST /api/goals/`` with the same ``X-API-Key`` file ``amebo-claw`` reads, so the
claws land under that key's org and there is one write path, not two.

Idempotent: a claw whose title already exists on this deploy is skipped, so
re-running after adding a seed only creates the new one.

Usage:
    python backend/scripts/seed_claws.py --notify slack:#channel [--dry-run]
    python backend/scripts/seed_claws.py --notify slack:#channel --only weekly-review-sweep

Environment (same contract as amebo-claw):
    AMEBO_CLI_URL       API base, default http://127.0.0.1:8000
    AMEBO_CLI_KEY_FILE  file holding the plain API key, default ~/.amebo/cli-key
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SEED_DIR = Path(__file__).resolve().parent.parent / "seeds" / "claws"


def _api_base() -> str:
    return os.environ.get("AMEBO_CLI_URL", "http://127.0.0.1:8000").rstrip("/")


def _api_key() -> str:
    path = Path(os.environ.get("AMEBO_CLI_KEY_FILE", "~/.amebo/cli-key")).expanduser()
    if not path.exists():
        sys.exit(f"no api key file at {path}. set AMEBO_CLI_KEY_FILE or create it (chmod 600).")
    key = path.read_text().strip()
    if not key:
        sys.exit(f"api key file at {path} is empty.")
    return key


def _req(method: str, path: str, body: Optional[dict] = None) -> Tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{_api_base()}{path}",
        data=data,
        method=method,
        headers={
            "X-API-Key": _api_key(),
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if data else {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"detail": raw}


def _seed_files(only: List[str]) -> List[Path]:
    if not SEED_DIR.is_dir():
        sys.exit(f"no seed directory at {SEED_DIR}")
    files = sorted(p for p in SEED_DIR.glob("*.json"))
    if only:
        wanted = {name.removesuffix(".json") for name in only}
        files = [p for p in files if p.stem in wanted]
        missing = wanted - {p.stem for p in files}
        if missing:
            sys.exit(f"no such seed: {', '.join(sorted(missing))}")
    if not files:
        sys.exit(f"no seed files in {SEED_DIR}")
    return files


def _existing_titles() -> set:
    """Titles already on this deploy, so a re-run creates nothing twice."""
    titles = set()
    status, payload = _req("GET", "/api/goals/?limit=200")
    if status != 200 or not isinstance(payload, list):
        sys.exit(f"cannot read existing claws ({status}): {json.dumps(payload)}")
    for goal in payload:
        if goal.get("title"):
            titles.add(goal["title"])
    return titles


def _body(seed: Dict[str, Any], seed_name: str, notify: str) -> Dict[str, Any]:
    claw = dict(seed["claw"])
    claw["notify_channel"] = notify
    config = dict(claw.get("config") or {})
    config["provenance"] = {"seed": f"backend/seeds/claws/{seed_name}.json"}
    claw["config"] = config
    return claw


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--notify", required=True,
                   help='notify channel for every seeded claw, e.g. "slack:#standup"')
    p.add_argument("--only", action="append", default=[],
                   help="seed name (filename without .json); repeat for several")
    p.add_argument("--dry-run", action="store_true",
                   help="print what would be created, write nothing")
    args = p.parse_args()

    files = _seed_files(args.only)
    existing = set() if args.dry_run else _existing_titles()
    created = skipped = failed = 0

    for path in files:
        try:
            seed = json.loads(path.read_text())
        except ValueError as e:
            print(f"BAD    {path.name}: not valid JSON: {e}")
            failed += 1
            continue
        if not isinstance(seed.get("claw"), dict) or not seed["claw"].get("title"):
            print(f"BAD    {path.name}: no claw.title")
            failed += 1
            continue

        title = seed["claw"]["title"]
        for need in seed.get("requires") or []:
            print(f"       needs: {need}")
        if title in existing:
            print(f"SKIP   {title}  (already on this deploy)")
            skipped += 1
            continue
        if args.dry_run:
            print(f"WOULD  {title}")
            continue

        status, payload = _req("POST", "/api/goals/", _body(seed, path.stem, args.notify))
        if status == 201 and isinstance(payload, dict):
            print(f"OK     {payload['id']}  {title}")
            created += 1
        else:
            print(f"FAIL   {title}  ({status}): {json.dumps(payload)}")
            failed += 1

    print(f"\n{created} created, {skipped} skipped, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
