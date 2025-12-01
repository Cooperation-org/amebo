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

## 📋 Prerequisites

- **Python 3.9+**
- **PostgreSQL 13+**
- **Slack App** with Bot Token, App Token, and Signing Secret
- **Anthropic API Key** for Claude AI

## 🚀 Quick Setup

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
createdb slack_helper

# Create user (optional)
psql -c "CREATE USER slack_user WITH PASSWORD 'your_password';"
psql -c "GRANT ALL PRIVILEGES ON DATABASE slack_helper TO slack_user;"
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
# Database
DATABASE_URL=postgresql://username:password@localhost:5432/slack_helper

# Anthropic AI
ANTHROPIC_API_KEY=your_anthropic_api_key_here

# JWT Security
JWT_SECRET_KEY=your_super_secret_jwt_key_here
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30

# Encryption
FERNET_KEY=your_fernet_encryption_key_here

# Email (for team invitations)
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your_email@gmail.com
SMTP_PASSWORD=your_app_password

# Development
DEBUG=True
CORS_ORIGINS=["http://localhost:3000"]
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
- **JWT Authentication** - Secure token-based authentication
- **Credential Encryption** - Fernet encryption for Slack tokens
- **Input Validation** - Pydantic models for request validation
- **CORS Protection** - Configurable cross-origin resource sharing
- **SQL Injection Prevention** - Parameterized queries

## 📊 Performance

- **Connection Pooling** - PostgreSQL connection pool (2-20 connections)
- **Async Operations** - FastAPI async/await for I/O operations
- **Background Tasks** - APScheduler for non-blocking operations
- **Caching** - ChromaDB vector caching for fast similarity search

## 🚀 Production Deployment

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

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `DATABASE_URL` | PostgreSQL connection string | Yes | - |
| `ANTHROPIC_API_KEY` | Anthropic Claude API key | Yes | - |
| `JWT_SECRET_KEY` | JWT signing secret | Yes | - |
| `FERNET_KEY` | Encryption key for credentials | Yes | - |
| `SMTP_SERVER` | Email server for invitations | No | - |
| `DEBUG` | Enable debug mode | No | `False` |
| `CORS_ORIGINS` | Allowed CORS origins | No | `[]` |

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