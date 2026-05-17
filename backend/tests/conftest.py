"""
Pytest configuration: set environment variables that the app expects before
any application module is imported.
"""

import os

# Required by src.api.auth_utils at import time. Tests do not exercise auth
# at the JWT level, so a fixed value is fine.
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only")

# DB tests hit the real `amebo` DB; if the test env doesn't provide DATABASE_URL,
# fall back to the same DSN the live service uses (read from the project .env).
if "DATABASE_URL" not in os.environ:
    env_path = "/opt/shared/repos/amebo/backend/.env"
    try:
        with open(env_path) as fh:
            for line in fh:
                if line.startswith("DATABASE_URL="):
                    os.environ["DATABASE_URL"] = line.split("=", 1)[1].strip()
                    break
    except OSError:
        os.environ["DATABASE_URL"] = "postgresql://test:test@127.0.0.1:1/test"

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
