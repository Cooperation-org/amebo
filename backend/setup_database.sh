#!/bin/bash
#
# Database Setup Script for Slack Helper (Amebo)
# Creates database, user, and grants necessary permissions
#
# Usage:
#   Local:  ./setup_database.sh
#   Server: docker-compose exec postgres bash /scripts/setup_database.sh
#

set -e  # Exit on error

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo "========================================================================"
echo "SLACK HELPER DATABASE SETUP"
echo "========================================================================"
echo ""

# Database configuration
DB_NAME="${POSTGRES_DB:-amebo}"
DB_USER="${POSTGRES_USER:-amebo}"
DB_PASSWORD="${POSTGRES_PASSWORD:-changeme123}"
DB_SUPERUSER="${DB_SUPERUSER:-postgres}"

echo -e "${BLUE}Configuration:${NC}"
echo "   Database: $DB_NAME"
echo "   User: $DB_USER"
echo "   Superuser: $DB_SUPERUSER"
echo ""

# Check if running inside Docker or locally
if [ -f /.dockerenv ]; then
    echo -e "${BLUE}Running inside Docker container${NC}"
    PSQL_CMD="psql -U $DB_SUPERUSER"
else
    echo -e "${BLUE}Running locally${NC}"
    PSQL_CMD="psql -U $DB_SUPERUSER postgres"
fi

echo ""
echo "========================================================================"
echo "Step 1: Creating database (if not exists)"
echo "========================================================================"

$PSQL_CMD << EOF
-- Create database if it doesn't exist
SELECT 'CREATE DATABASE $DB_NAME'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$DB_NAME')\gexec
EOF

if [ $? -eq 0 ]; then
    echo -e "${GREEN}SUCCESS: Database '$DB_NAME' ready${NC}"
else
    echo -e "${RED}ERROR: Failed to create database${NC}"
    exit 1
fi

echo ""
echo "========================================================================"
echo "Step 2: Creating user (if not exists)"
echo "========================================================================"

$PSQL_CMD << EOF
-- Create user if it doesn't exist
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_user WHERE usename = '$DB_USER') THEN
        CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';
        RAISE NOTICE 'Created user: $DB_USER';
    ELSE
        RAISE NOTICE 'User already exists: $DB_USER';
    END IF;
END
\$\$;
EOF

if [ $? -eq 0 ]; then
    echo -e "${GREEN}SUCCESS: User '$DB_USER' ready${NC}"
else
    echo -e "${RED}ERROR: Failed to create user${NC}"
    exit 1
fi

echo ""
echo "========================================================================"
echo "Step 3: Granting permissions"
echo "========================================================================"

$PSQL_CMD << EOF
-- Grant database privileges
GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;

-- Connect to database and grant schema privileges
\c $DB_NAME

-- Grant schema privileges
GRANT ALL ON SCHEMA public TO $DB_USER;

-- Grant privileges on existing tables
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO $DB_USER;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO $DB_USER;

-- Set default privileges for future tables
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO $DB_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO $DB_USER;
EOF

if [ $? -eq 0 ]; then
    echo -e "${GREEN}SUCCESS: Permissions granted${NC}"
else
    echo -e "${RED}ERROR: Failed to grant permissions${NC}"
    exit 1
fi

echo ""
echo "========================================================================"
echo "Step 4: Verifying setup"
echo "========================================================================"

$PSQL_CMD -d $DB_NAME << EOF
-- List tables
\dt

-- Check user can query
SELECT 'Connection test: OK' as status;
EOF

if [ $? -eq 0 ]; then
    echo -e "${GREEN}SUCCESS: Verification successful${NC}"
else
    echo -e "${RED}ERROR: Verification failed${NC}"
    exit 1
fi

echo ""
echo "========================================================================"
echo -e "${GREEN}DATABASE SETUP COMPLETE${NC}"
echo "========================================================================"
echo ""
echo "Connection details:"
echo "  DATABASE_URL=postgresql://$DB_USER:$DB_PASSWORD@localhost:5432/$DB_NAME"
echo ""
echo "Next steps:"
echo "  1. Load schema: psql -U $DB_USER -d $DB_NAME -f src/db/schema.sql"
echo "  2. Or use migration: python migrate_slack_padi.py"
echo ""
