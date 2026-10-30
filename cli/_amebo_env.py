"""Shared by the amebo-* wrappers amebo-max runs: read named keys from
backend/.env, so credentials stay inside the wrapper process."""
import sys
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / "backend" / ".env"


def read_env(*keys):
    vals = {}
    for line in ENV_FILE.read_text().splitlines():
        k, _, v = line.partition("=")
        if k in keys:
            vals[k] = v.strip().strip('"')
    missing = [k for k in keys if not vals.get(k)]
    if missing:
        sys.exit(f"missing in backend/.env: {', '.join(missing)}")
    return vals
