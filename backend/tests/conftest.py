"""
Pytest configuration: set environment variables that the app expects before
any application module is imported.
"""

import os

# Required by src.api.auth_utils at import time. Tests do not exercise auth
# at the JWT level, so a fixed value is fine.
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:1/test")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
