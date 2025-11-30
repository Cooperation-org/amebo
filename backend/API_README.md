# Slack Helper Bot - FastAPI Backend

Backend API for Slack Helper Bot with authentication, document management, Q&A, and Slack OAuth integration.

## Quick Start

### 1. Install Dependencies

```bash
# Using virtual environment (recommended)
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your credentials
```

Required environment variables:
- `JWT_SECRET_KEY` - Generate a secure random key (min 32 chars)
- `DATABASE_URL` - PostgreSQL connection string
- `ANTHROPIC_API_KEY` - For Q&A functionality
- `SLACK_CLIENT_ID` & `SLACK_CLIENT_SECRET` - For OAuth (optional for now)

### 3. Initialize Database

```bash
# Run schema migrations
python scripts/init_db.py
```

This creates:
- Organizations and users tables (auth system)
- Slack workspaces and messages tables
- Documents table for uploaded files
- Audit logs and usage metrics

### 4. Start API Server

```bash
# Development mode (with auto-reload)
python src/api/main.py

# Or using uvicorn directly
uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000
```

API will be available at: `http://localhost:8000`

## API Documentation

### Interactive Docs

- **Swagger UI**: http://localhost:8000/api/docs
- **ReDoc**: http://localhost:8000/api/redoc

### Endpoints Overview

#### Authentication (`/api/auth`)
- `POST /signup` - Create new organization and owner user
- `POST /login` - Login with email/password
- `POST /refresh` - Refresh access token
- `GET /me` - Get current user info

#### Organizations (`/api/organizations`)
- `GET /me` - Get organization details
- `PATCH /me` - Update organization (admin only)
- `GET /users` - List organization users
- `POST /users/invite` - Invite new user (admin only)
- `GET /stats` - Get dashboard statistics

#### Documents (`/api/documents`)
- `POST /upload` - Upload document (PDF, DOCX, TXT, MD) *[Coming soon]*
- `GET /` - List all documents
- `DELETE /{document_id}` - Delete document

#### Q&A (`/api/qa`)
- `POST /ask` - Ask a question (searches Slack + documents) *[Coming soon]*

#### Slack Integration (`/api/slack`)
- `GET /install` - Start Slack OAuth flow *[Coming soon]*
- `GET /callback` - OAuth callback handler
- `GET /workspaces` - List connected workspaces
- `DELETE /workspaces/{workspace_id}` - Disconnect workspace

## Authentication Flow

### 1. Signup (Creates Org + User)

```bash
curl -X POST http://localhost:8000/api/auth/signup \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@company.com",
    "password": "SecurePass123",
    "full_name": "Admin User",
    "org_name": "My Company"
  }'
```

Response:
```json
{
  "access_token": "eyJhbGc...",
  "refresh_token": "eyJhbGc...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

### 2. Login

```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@company.com",
    "password": "SecurePass123"
  }'
```

### 3. Authenticated Requests

Include access token in Authorization header:

```bash
curl -X GET http://localhost:8000/api/auth/me \
  -H "Authorization: Bearer eyJhbGc..."
```

### 4. Token Refresh

```bash
curl -X POST http://localhost:8000/api/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{
    "refresh_token": "eyJhbGc..."
  }'
```

## Database Schema

### Auth Tables
- `organizations` - Companies using the platform
- `platform_users` - User accounts with roles (owner, admin, member, viewer)
- `org_workspaces` - Links organizations to Slack workspaces
- `documents` - Uploaded company documents
- `api_keys` - API keys for programmatic access
- `refresh_tokens` - JWT refresh token storage
- `audit_logs` - Action tracking
- `usage_metrics` - Billing/limit tracking

### Slack Tables
- `workspaces` - Slack workspace metadata
- `installations` - Bot installation tracking
- `message_metadata` - Message metadata (text stored in ChromaDB)
- `reactions` - Reaction tracking
- `users` - Slack user profiles
- `channels` - Channel information
- And more...

## User Roles

- **owner** - Full access, cannot be removed
- **admin** - Manage users, settings, and workspaces
- **member** - Use Q&A, view documents
- **viewer** - Read-only access

## Development

### Testing Authentication

```bash
# 1. Signup
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/signup \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "Test1234",
    "full_name": "Test User",
    "org_name": "Test Org"
  }' | jq -r '.access_token')

# 2. Get current user
curl -X GET http://localhost:8000/api/auth/me \
  -H "Authorization: Bearer $TOKEN"

# 3. Get organization
curl -X GET http://localhost:8000/api/organizations/me \
  -H "Authorization: Bearer $TOKEN"

# 4. Get dashboard stats
curl -X GET http://localhost:8000/api/organizations/stats \
  -H "Authorization: Bearer $TOKEN"
```

### Health Check

```bash
curl http://localhost:8000/health
```

## Next Steps

1. ✅ **Backend Foundation** - Complete!
   - FastAPI setup
   - JWT authentication
   - Organization/user management
   - Database schema

2. **Implement Document Upload** (next)
   - File upload handling
   - PDF/DOCX parsing
   - ChromaDB storage

3. **Integrate Q&A Service**
   - Connect existing QAService
   - Multi-source search (Slack + documents)

4. **Slack OAuth Flow**
   - OAuth installation
   - Token management
   - Real-time event listener

5. **Frontend Development**
   - Next.js dashboard
   - Login/signup pages
   - Q&A interface

## Project Structure

```
src/api/
├── main.py              # FastAPI app
├── auth_utils.py        # JWT & password utilities
├── models.py            # Pydantic models
└── routes/
    ├── auth.py          # Authentication endpoints
    ├── organizations.py # Org management
    ├── documents.py     # Document upload (stub)
    ├── qa.py           # Q&A endpoints (stub)
    └── slack_oauth.py   # Slack integration (stub)

src/db/
├── schema.sql          # Slack data tables
└── schema_auth.sql     # Auth & org tables

scripts/
└── init_db.py          # Database initialization
```

## Troubleshooting

### Database Connection Issues

Check your PostgreSQL connection:
```bash
psql $DATABASE_URL
```

### Port Already in Use

Change port in command:
```bash
uvicorn src.api.main:app --reload --port 8001
```

### JWT Secret Not Set

Generate a secure secret:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Add to `.env`:
```
JWT_SECRET_KEY=<generated-secret>
```
