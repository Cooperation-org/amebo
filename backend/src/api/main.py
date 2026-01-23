"""
FastAPI Application - Slack Helper Bot Backend
Handles authentication, document management, Q&A, and Slack OAuth
"""

import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging
import time

from src.api.routes import auth, documents, qa, slack_oauth, organizations, workspaces, dev_auth, team
from src.api.middleware.rate_limit import RateLimitMiddleware
from src.db.connection import DatabaseConnection

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Slack Helper Bot API",
    description="Backend API for Slack Helper Bot - Q&A, Document Management, and Slack Integration",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/openapi.json"  # FastAPI serves this at root, not under /api
)

# CORS Configuration
# Configure allowed origins via CORS_ORIGINS environment variable (comma-separated)
# Example: CORS_ORIGINS=http://localhost:3000,https://myapp.vercel.app
cors_origins_env = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:3001")
cors_origins = [origin.strip() for origin in cors_origins_env.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
)

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


# Slack Events endpoint (at root level, not under /api)
from src.api.routes.slack_oauth import slack_events
app.add_api_route("/slack/events", slack_events, methods=["POST"], tags=["Slack Events"])


# Include routers
# Use real authentication by default
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])

# Dev auth is only included if explicitly enabled via environment variable
import os
if os.getenv("DEV_AUTH_ENABLED", "false").lower() == "true":
    app.include_router(dev_auth.router, prefix="/api/dev-auth", tags=["Development Auth"])
app.include_router(organizations.router, prefix="/api/organizations", tags=["Organizations"])
app.include_router(workspaces.router, prefix="/api/workspaces", tags=["Workspaces"])
app.include_router(documents.router, prefix="/api/documents", tags=["Documents"])
app.include_router(qa.router, prefix="/api/qa", tags=["Q&A"])
app.include_router(slack_oauth.router, prefix="/api/slack", tags=["Slack Integration"])

# Import admin and team routes
from src.api.routes import admin
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
app.include_router(team.router, prefix="/api/team", tags=["Team Management"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
