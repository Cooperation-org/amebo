# Amebo - Backend

🐍 **FastAPI Backend** - High-performance Python API server with multi-tenant architecture and AI-powered Q&A capabilities.

## 🏗️ Architecture Overview

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   API Routes    │    │    Services     │    │   Database      │
│                 │    │                 │    │                 │
│ • Auth          │◄──►│ • QA Service    │◄──►│ • PostgreSQL    │
│ • Workspaces    │    │ • Document Svc  │    │ • ChromaDB      │
│ • Documents     │    │ • Slack Svc     │    │ • Encryption    │
│ • Team Mgmt     │    │ • Backfill Svc  │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## Prerequisites

- **Python 3.9+**
- **PostgreSQL 13+**
- **Slack App** with Bot Token, App Token, and Signing Secret
- **Anthropic API Key** for Claude AI

## Quick Setup

### 1. Environment Setup

```bash
# Clone and navigate
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Database Setup

```bash
# Install PostgreSQL (macOS)
brew install postgresql
brew services start postgresql

# Create database
createdb amebo

# Create user (optional)
psql -c "CREATE USER amebo_user WITH PASSWORD 'your_password';"
psql -c "GRANT ALL PRIVILEGES ON DATABASE amebo TO amebo_user;"
```

### 3. Environment Configuration

```bash
# Copy environment template
cp .env.example .env

# Edit .env file with your credentials
nano .env
```

**Required Environment Variables:**

```env
# ==============================================================================
# REQUIRED - App will not start without these
# ==============================================================================

# Database
DATABASE_URL=postgresql://username:password@localhost:5432/amebo

# Anthropic AI
ANTHROPIC_API_KEY=your_anthropic_api_key_here

# Security Keys (REQUIRED - generate with command below)
# python -c "import secrets; print(secrets.token_urlsafe(32))"
JWT_SECRET_KEY=your_generated_secret_key_here
ENCRYPTION_KEY=your_generated_encryption_key_here

# ==============================================================================
# OPTIONAL - Have sensible defaults
# ==============================================================================

# CORS - comma-separated list of allowed origins
CORS_ORIGINS=http://localhost:3000,http://localhost:3001

# Rate Limiting (requests per window)
RATE_LIMIT_AUTH_MAX=5          # Auth endpoints (login) - strict to prevent brute force
RATE_LIMIT_AUTH_WINDOW=60      # Window in seconds
RATE_LIMIT_API_MAX=100         # General API endpoints
RATE_LIMIT_API_WINDOW=60
RATE_LIMIT_UPLOAD_MAX=10       # File upload endpoints
RATE_LIMIT_UPLOAD_WINDOW=60

# File Upload Limits
MAX_UPLOAD_SIZE_MB=50          # Maximum file size in MB
MAX_FILES_PER_REQUEST=10       # Maximum files per upload request

# Email (for team invitations - optional)
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=

# Debug mode (always false in production)
DEBUG=false

# ==============================================================================
# DEVELOPMENT ONLY - Never enable in production
# ==============================================================================
# DEV_AUTH_ENABLED=false       # Set to true to enable dev auth endpoints
# DEV_AUTH_EMAIL=              # Email for dev login
# DEV_AUTH_PASSWORD=           # Password for dev login
```

### Generating Secure Keys

**Important:** You must generate secure random keys for `JWT_SECRET_KEY` and `ENCRYPTION_KEY`.
The app will refuse to start without them.

```bash
# Generate a secure key (run twice, once for each)
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 4. Database Initialization

```bash
# Run database migrations (if available)
python -m alembic upgrade head

# Or create tables manually
python -c "
from src.db.connection import DatabaseConnection
from src.db.schema import create_tables
create_tables()
"
```

### 5. Start the Server

```bash
# Development server
python run_server.py

# Or using uvicorn directly
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

## 🔧 Configuration

### Slack App Setup

1. **Create Slack App** at https://api.slack.com/apps
2. **Enable Socket Mode** and generate App Token
3. **Add Bot Scopes**:
   - `channels:history`
   - `channels:read`
   - `chat:write`
   - `commands`
   - `groups:history`
   - `groups:read`
   - `im:history`
   - `im:read`
   - `mpim:history`
   - `mpim:read`
   - `users:read`

4. **Create Slash Commands**:
   - `/ask` - Ask questions to the AI
   - `/askall` - Ask questions across all channels

5. **Install to Workspace** and copy tokens

### ChromaDB Setup

ChromaDB is automatically initialized when the application starts. Data is stored in `./chroma_db/` directory.

```bash
# ChromaDB will create collections automatically
# Collections are named: org_{org_id}_workspace_{workspace_id}
```

## 📁 Project Structure

```
backend/
├── src/
│   ├── api/                    # API routes and middleware
│   │   ├── routes/
│   │   │   ├── auth.py        # Authentication endpoints
│   │   │   ├── workspaces.py  # Workspace management
│   │   │   ├── qa.py          # Q&A endpoints
│   │   │   ├── documents.py   # Document upload/management
│   │   │   └── team.py        # Team management
│   │   └── middleware/
│   │       └── auth.py        # JWT authentication middleware
│   ├── services/              # Business logic services
│   │   ├── qa_service.py      # AI Q&A processing
│   │   ├── document_service.py # Document processing
│   │   ├── slack_service.py   # Slack API integration
│   │   ├── backfill_service.py # Message backfilling
│   │   └── email_service.py   # Email notifications
│   ├── db/                    # Database layer
│   │   ├── connection.py      # Database connection pool
│   │   └── schema.py          # Database schema
│   └── models/                # Pydantic models
│       └── auth.py           # Authentication models
├── requirements.txt           # Python dependencies
├── run_server.py             # Development server
├── start_slack_bot.py        # Slack bot starter
└── .env.example              # Environment template
```

## 🔌 API Endpoints

### Authentication
- `POST /api/auth/login` - User login
- `POST /api/auth/signup` - User registration
- `GET /api/auth/me` - Get current user
- `POST /api/auth/logout` - User logout

### Workspaces
- `GET /api/workspaces` - List workspaces
- `POST /api/workspaces` - Add workspace
- `PUT /api/workspaces/{id}` - Update workspace
- `DELETE /api/workspaces/{id}` - Delete workspace
- `POST /api/workspaces/{id}/backfill` - Trigger backfill

### Q&A
- `POST /api/qa/ask` - Ask AI question

### Documents
- `POST /api/documents/upload` - Upload documents
- `GET /api/documents` - List documents
- `DELETE /api/documents/clear-all` - Clear all documents

### Team Management
- `GET /api/team/members` - List team members
- `POST /api/team/invite` - Invite user
- `PUT /api/team/members/{id}/role` - Update user role

## 🧪 Testing

```bash
# Run tests
pytest

# Run with coverage
pytest --cov=src

# Test specific module
pytest tests/test_qa_service.py
```

## 🐛 Debugging

### Common Issues

1. **Database Connection Error**
   ```bash
   # Check PostgreSQL is running
   brew services list | grep postgresql
   
   # Test connection
   psql -d slack_helper -c "SELECT 1;"
   ```

2. **ChromaDB Permission Error**
   ```bash
   # Fix permissions
   chmod -R 755 ./chroma_db/
   ```

3. **Slack API Rate Limits**
   ```bash
   # Check logs for rate limit errors
   tail -f logs/app.log
   ```

### Logging

```python
# Enable debug logging
import logging
logging.basicConfig(level=logging.DEBUG)
```

## 🔒 Security Features

- **Multi-tenant Architecture** - Complete data isolation between organizations
- **JWT Authentication** - Secure token-based authentication with required secret keys
- **Credential Encryption** - Fernet encryption for Slack tokens (stored encrypted at rest)
- **Rate Limiting** - Configurable per-endpoint rate limits to prevent brute force and abuse
- **Input Validation** - Pydantic models for request validation
- **File Upload Protection** - Size limits, file count limits, and content type validation
- **CORS Protection** - Configurable cross-origin resource sharing (no wildcards)
- **SQL Injection Prevention** - Parameterized queries throughout
- **Safe Error Messages** - Internal errors are logged but not exposed to clients

## 📊 Performance

- **Connection Pooling** - PostgreSQL connection pool (2-20 connections)
- **Async Operations** - FastAPI async/await for I/O operations
- **Background Tasks** - APScheduler for non-blocking operations
- **Caching** - ChromaDB vector caching for fast similarity search

## Production Deployment

```bash
# Install production dependencies
pip install gunicorn

# Run with Gunicorn
gunicorn src.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000

# Or use Docker
docker build -t slack-helper-backend .
docker run -p 8000:8000 slack-helper-backend
```

## 📝 Environment Variables Reference

### Required Variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string |
| `ANTHROPIC_API_KEY` | Anthropic Claude API key |
| `JWT_SECRET_KEY` | JWT signing secret (generate with `secrets.token_urlsafe(32)`) |
| `ENCRYPTION_KEY` | Credential encryption key (generate with `secrets.token_urlsafe(32)`) |

### Optional Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `CORS_ORIGINS` | Comma-separated allowed origins | `http://localhost:3000,http://localhost:3001` |
| `DEBUG` | Enable debug mode | `false` |
| `RATE_LIMIT_AUTH_MAX` | Max auth requests per window | `5` |
| `RATE_LIMIT_AUTH_WINDOW` | Auth rate limit window (seconds) | `60` |
| `RATE_LIMIT_API_MAX` | Max API requests per window | `100` |
| `RATE_LIMIT_API_WINDOW` | API rate limit window (seconds) | `60` |
| `RATE_LIMIT_UPLOAD_MAX` | Max upload requests per window | `10` |
| `RATE_LIMIT_UPLOAD_WINDOW` | Upload rate limit window (seconds) | `60` |
| `MAX_UPLOAD_SIZE_MB` | Maximum file upload size | `50` |
| `MAX_FILES_PER_REQUEST` | Maximum files per upload | `10` |
| `SMTP_SERVER` | Email server for invitations | - |
| `SMTP_PORT` | Email server port | `587` |
| `SMTP_USERNAME` | Email username | - |
| `SMTP_PASSWORD` | Email password | - |

### Development Only Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DEV_AUTH_ENABLED` | Enable dev auth endpoints | `false` |
| `DEV_AUTH_EMAIL` | Email for dev login | - |
| `DEV_AUTH_PASSWORD` | Password for dev login | - |

> **Never enable `DEV_AUTH_ENABLED` in production!**

## 🤝 Contributing

1. Follow PEP 8 style guidelines
2. Add type hints to all functions
3. Write tests for new features
4. Update documentation

## 📚 Additional Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [ChromaDB Documentation](https://docs.trychroma.com/)
- [Slack API Documentation](https://api.slack.com/)
- [Anthropic Claude API](https://docs.anthropic.com/)