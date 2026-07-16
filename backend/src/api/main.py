"""
FastAPI Application - Slack Helper Bot Backend
Handles authentication, document management, Q&A, and Slack OAuth
"""

import os
import pathlib
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
import logging
import time

from src.api.routes import auth, documents, qa, slack_oauth, organizations, workspaces, dev_auth, team, bindings, chat, embeddings, goals, connections, digest, intentions, pending_actions, org_provision, whiteboard
from src.api.middleware.rate_limit import RateLimitMiddleware
from src.api.middleware.auth_gate import AuthGateMiddleware
from src.db.connection import DatabaseConnection

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
# Schema-discovery endpoints (docs, redoc, openapi) are disabled by default
# to avoid leaking the full route surface on internal networks. Set
# ENABLE_DOCS=true to re-enable for local development.
_docs_enabled = os.getenv("ENABLE_DOCS", "false").lower() == "true"
app = FastAPI(
    title="Slack Helper Bot API",
    description="Backend API for Slack Helper Bot - Q&A, Document Management, and Slack Integration",
    version="1.0.0",
    docs_url="/api/docs" if _docs_enabled else None,
    redoc_url="/api/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

# CORS Configuration
# Configure allowed origins via CORS_ORIGINS environment variable (comma-separated)
# Example: CORS_ORIGINS=http://localhost:3000,https://myapp.vercel.app
cors_origins_env = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:3001,https://demos.linkedtrust.us")
cors_origins = [origin.strip() for origin in cors_origins_env.split(",") if origin.strip()]

# Global auth gate: external (nginx-edge) callers must authenticate; internal
# loopback callers (Claude Code on the box) are trusted. Added BEFORE CORS so
# CORS wraps it and 401 responses still carry CORS headers for the browser.
app.add_middleware(AuthGateMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)

# Proxy headers middleware - trust X-Forwarded-Proto/X-Forwarded-For from reverse proxy
# This ensures redirects use HTTPS when behind a load balancer/reverse proxy
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["*"])

# Rate limiting middleware (applied after CORS)
# Configure limits via environment variables:
# - RATE_LIMIT_AUTH_MAX / RATE_LIMIT_AUTH_WINDOW (default: 5 requests per 60s)
# - RATE_LIMIT_API_MAX / RATE_LIMIT_API_WINDOW (default: 100 requests per 60s)
# - RATE_LIMIT_UPLOAD_MAX / RATE_LIMIT_UPLOAD_WINDOW (default: 10 requests per 60s)
app.add_middleware(RateLimitMiddleware)


# Request timing middleware
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response


# Exception handlers
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "message": "An unexpected error occurred"
        }
    )


# Startup/Shutdown events
@app.on_event("startup")
async def startup_event():
    """Initialize resources on startup"""
    logger.info("Starting Slack Helper Bot API...")
    DatabaseConnection.initialize_pool()
    logger.info("Database connection pool initialized")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup resources on shutdown"""
    logger.info("Shutting down Slack Helper Bot API...")
    DatabaseConnection.close_all_connections()
    logger.info("Database connections closed")


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "slack-helper-bot-api",
        "version": "1.0.0"
    }


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "service": "Slack Helper Bot API",
        "version": "1.0.0",
        "docs": "/api/docs",
        "health": "/health"
    }


# Slack Events and Commands endpoints (at root level, not under /api)
from src.api.routes.slack_oauth import slack_events, slack_commands
app.add_api_route("/slack/events", slack_events, methods=["POST"], tags=["Slack Events"])
app.add_api_route("/slack/commands", slack_commands, methods=["POST"], tags=["Slack Commands"])


# Routable per-claw view (per view session 2026-06-04: every viewable thing
# gets a routable URL so the user can copy from UI and paste into voice).
# The page mounts the embed bundle's singular claw component. Auth happens
# in the browser via credentials: 'include'; if the user is not signed in,
# the bundle will surface a 401 inline. The URL itself is always live.
from fastapi.responses import HTMLResponse
import html as _html

_CLAW_PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>amebo claw {short_id}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  :root {{ color-scheme: light dark; }}
  body {{
    font-family: system-ui, -apple-system, sans-serif;
    max-width: 760px; margin: 2rem auto; padding: 0 1rem;
    line-height: 1.5;
  }}
  header {{ margin-bottom: 1rem; opacity: 0.7; font-size: 13px; }}
  header code {{ font-family: ui-monospace, monospace; }}
  .uri {{ font-family: ui-monospace, monospace; font-size: 12px; opacity: 0.7; }}
  amebo-goal {{ display: block; margin-top: 1rem; }}
</style>
</head>
<body>
<header>
  amebo claw · <code>{full_id}</code> ·
  <span class="uri">amebo:claw/{full_id}</span>
</header>
<amebo-goal data-up="" data-path="{full_id}"></amebo-goal>
<script src="/embed/amebo.js"></script>
</body>
</html>
"""


@app.get("/claws/{claw_id}", include_in_schema=False)
async def claw_view(claw_id: str) -> HTMLResponse:
    """Routable human-viewable page for one claw.

    Renders the singular embed component (still registered as <amebo-goal>
    pending its rename). Auth is browser-side; no claw data is rendered
    server-side, so this endpoint does not leak across orgs.
    """
    safe_id = _html.escape(claw_id)
    short = _html.escape(claw_id[:8])
    body = _CLAW_PAGE_TEMPLATE.format(full_id=safe_id, short_id=short)
    return HTMLResponse(content=body)


# Include routers
# Use real authentication by default
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])

# Dev auth is only included if explicitly enabled via environment variable
import os
if os.getenv("DEV_AUTH_ENABLED", "false").lower() == "true":
    app.include_router(dev_auth.router, prefix="/api/dev-auth", tags=["Development Auth"])
app.include_router(organizations.router, prefix="/api/organizations", tags=["Organizations"])
# S2S org provisioning (GovKit accept, earnkit add-team) — self-gated by the
# static AMEBO_S2S_TOKEN, not user JWTs. See routes/org_provision.py.
app.include_router(org_provision.router, prefix="/api/orgs", tags=["Org Provisioning (S2S)"])
app.include_router(workspaces.router, prefix="/api/workspaces", tags=["Workspaces"])
app.include_router(documents.router, prefix="/api/documents", tags=["Documents"])
app.include_router(qa.router, prefix="/api/qa", tags=["Q&A"])
app.include_router(slack_oauth.router, prefix="/api/slack", tags=["Slack Integration"])

# Import admin and team routes
from src.api.routes import admin
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
app.include_router(team.router, prefix="/api/team", tags=["Team Management"])
app.include_router(bindings.router, prefix="/api/bindings", tags=["Bindings"])
app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
app.include_router(embeddings.router, prefix="/api/embeddings", tags=["Embeddings"])
app.include_router(goals.router, prefix="/api/goals", tags=["Goals"])
app.include_router(connections.router, prefix="/api/connections", tags=["Connections"])
app.include_router(digest.router, prefix="/api/digest", tags=["Digest"])
app.include_router(intentions.router, prefix="/api/intentions", tags=["Intentions"])
app.include_router(pending_actions.router, prefix="/api/pending-actions", tags=["Pending Actions"])
app.include_router(whiteboard.router, prefix="/api/whiteboard", tags=["Whiteboard"])
# /connect/{short_code} is the user-facing OAuth entry; mounted at root so
# the link looks like a normal short URL when sent through chat/email.
app.include_router(connections.public_router, tags=["Connections (Public)"])

# Coding-agent orchestration is experimental and only mounted when explicitly
# enabled. Inert (route absent) unless CODING_ENABLED=true.
if os.getenv("CODING_ENABLED", "false").lower() == "true":
    from src.api.routes import coding
    app.include_router(coding.router, prefix="/api/coding", tags=["Coding"])

# Embed bundle: ships <amebo-ask> / <amebo-goal> / <amebo-digest> as a
# single static JS file. Host shells (abra view, demos) load it once;
# components fetch via ${data-up}/api/... so amebo's host is never baked
# into the embedding page.
_EMBED_DIR = pathlib.Path(__file__).resolve().parents[3] / "embed"
if _EMBED_DIR.is_dir():
    app.mount("/embed", StaticFiles(directory=str(_EMBED_DIR)), name="embed")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
