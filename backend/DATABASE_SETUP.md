# Database Setup Guide

This guide shows how to set up the PostgreSQL database for Slack Helper (Amebo).

## Local Setup (MacBook)

### Option 1: Using Shell Script

```bash
cd backend
./setup_database.sh
```

### Option 2: Using SQL File

```bash
cd backend
psql -U postgres postgres -f setup_database.sql
```

### Option 3: Manual Setup

```bash
# Connect to postgres
psql postgres

# Run these commands:
CREATE DATABASE amebo;
CREATE USER amebo WITH PASSWORD 'changeme123';
GRANT ALL PRIVILEGES ON DATABASE amebo TO amebo;
\c amebo
GRANT ALL ON SCHEMA public TO amebo;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO amebo;
\q
```

## Server Setup (Docker)

### Method 1: Using SQL File (Recommended)

```bash
# On server, in /opt/amebo/amebo directory
cat backend/setup_database.sql | docker-compose exec -T postgres psql -U postgres
```

### Method 2: Using Shell Script

```bash
# Copy script into container and run
docker cp backend/setup_database.sh amebo-postgres:/tmp/
docker-compose exec postgres bash /tmp/setup_database.sh
```

### Method 3: Interactive

```bash
# Connect to postgres container
docker-compose exec postgres psql -U postgres

# Then run:
CREATE USER amebo WITH PASSWORD 'changeme123';
GRANT ALL PRIVILEGES ON DATABASE amebo TO amebo;
\c amebo
GRANT ALL ON SCHEMA public TO amebo;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO amebo;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO amebo;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO amebo;
\q
```

## After Database Setup

### Load Schema

**Local:**
```bash
cd backend
psql -U amebo -d amebo -f src/db/schema.sql
```

**Server:**
```bash
cat backend/src/db/schema.sql | docker-compose exec -T postgres psql -U postgres -d amebo
```

### Verify Setup

**Local:**
```bash
psql -U amebo -d amebo -c "\dt"
```

**Server:**
```bash
docker-compose exec postgres psql -U amebo -d amebo -c "\dt"
```

Should show all tables:
- workspaces
- installations
- message_metadata
- channels
- users
- backfill_schedules
- conversation_history
- etc.

## Environment Variables

Update `.env` file with:

```bash
# Local
DATABASE_URL=postgresql://amebo:changeme123@localhost:5432/amebo

# Server (Docker)
DATABASE_URL=postgresql://amebo:changeme123@postgres:5432/amebo
```

## Troubleshooting

### "role amebo does not exist"

Run the setup script again:
```bash
cat backend/setup_database.sql | docker-compose exec -T postgres psql -U postgres
```

### "must be owner of table"

Tables were created by different user. Grant permissions:
```bash
docker-compose exec postgres psql -U postgres -d amebo << 'EOF'
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO amebo;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO amebo;
EOF
```

### Fresh Start

**Local:**
```bash
psql postgres -c "DROP DATABASE IF EXISTS amebo;"
./setup_database.sh
psql -U amebo -d amebo -f src/db/schema.sql
```

**Server:**
```bash
docker-compose exec postgres psql -U postgres -c "DROP DATABASE IF EXISTS amebo;"
cat backend/setup_database.sql | docker-compose exec -T postgres psql -U postgres
cat backend/src/db/schema.sql | docker-compose exec -T postgres psql -U postgres -d amebo
```

## Files

- `setup_database.sh` - Shell script for automated setup
- `setup_database.sql` - SQL-only setup (works anywhere)
- `src/db/schema.sql` - Complete database schema
- `migrate_slack_padi.py` - Migration script for schema updates
