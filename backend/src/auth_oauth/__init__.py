"""
OAuth login support — Sign in with Google (more providers later).

Public surface:
    from src.auth_oauth import resolve_google_identity, GoogleProfile

Everything else (Google library internals, token verification) is private.
"""

from src.auth_oauth.google_login import (
    GoogleProfile,
    resolve_google_identity,
    GoogleLoginError,
)


__all__ = ["GoogleProfile", "resolve_google_identity", "GoogleLoginError"]
