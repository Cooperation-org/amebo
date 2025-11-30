# Slack Helper Bot - Backend

Python FastAPI backend for Slack Helper Bot SaaS platform.

## Quick Start

```bash
# From the backend/ directory
cd backend

# Activate virtual environment
source venv/bin/activate

# Install dependencies (if needed)
pip install -r requirements.txt

# Set environment variables
cp .env.example .env
# Edit .env with your credentials

# Run database migrations
psql -U $POSTGRES_USER -d slack_helper -f migrations/001_initial_schema.sql
psql -U $POSTGRES_USER -d slack_helper -f migrations/002_update_schema.sql
# ... run all migrations in order

# Start the unified backend (all services)
python -m src.main
```

This starts:
- FastAPI server on http://localhost:8000
- Slack Socket Mode listener
- Background task scheduler (APScheduler)

## Project Structure

```
backend/
├── src/
│   ├── api/              # FastAPI routes and models
│   │   ├── routes/       # API endpoints
│   │   ├── middleware/   # Auth, workspace isolation
│   │   └── main.py       # FastAPI app
│   ├── services/         # Business logic
│   │   ├── qa_service.py
│   │   ├── scheduler.py
│   │   ├── backfill_service.py
│   │   └── credential_service.py
│   ├── db/               # Database clients
│   │   ├── connection.py
│   │   └── chromadb_client.py
│   ├── utils/            # Utilities
│   │   └── encryption.py
│   └── main.py           # Unified entry point
├── migrations/           # SQL migrations
├── tests/                # Test suite
├── scripts/              # Utility scripts
├── requirements.txt      # Python dependencies
└── .env                  # Environment variables
```

## API Documentation

Once running, visit:
- Swagger UI: http://localhost:8000/api/docs
- ReDoc: http://localhost:8000/redoc

## Environment Variables

Required:
- `DATABASE_URL` - PostgreSQL connection string
- `POSTGRES_USER` - Database user
- `SLACK_BOT_TOKEN` - Slack bot token (xoxb-...)
- `SLACK_APP_TOKEN` - Slack app token (xapp-...)
- `ANTHROPIC_API_KEY` - Claude API key
- `JWT_SECRET_KEY` - Secret for JWT tokens
- `ENCRYPTION_KEY` - Key for encrypting credentials

## Development

```bash
# Run tests
pytest tests/

# Run specific test file
pytest tests/test_workspace_isolation.py

# Test encryption
python -m src.utils.encryption

# Format code
black src/

# Lint
flake8 src/
```

## Database

PostgreSQL + ChromaDB hybrid storage:
- PostgreSQL: Metadata, users, organizations
- ChromaDB: Vector embeddings for semantic search

## Security

- 4-layer workspace isolation
- Encrypted credentials at rest (Fernet)
- JWT authentication
- Role-based access control

## Deployment

See root README for deployment instructions.
