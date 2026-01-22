--
-- Database Setup SQL for Slack Helper (Amebo)
-- Creates database, user, and grants permissions
--
-- Usage on server:
--   cat setup_database.sql | docker-compose exec -T postgres psql -U postgres
--

-- Create database if it doesn't exist
SELECT 'CREATE DATABASE amebo'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'amebo')\gexec

-- Create user if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_user WHERE usename = 'amebo') THEN
        CREATE USER amebo WITH PASSWORD 'changeme123';
        RAISE NOTICE 'Created user: amebo';
    ELSE
        RAISE NOTICE 'User already exists: amebo';
    END IF;
END
$$;

-- Grant database privileges
GRANT ALL PRIVILEGES ON DATABASE amebo TO amebo;

-- Connect to amebo database
\c amebo

-- Grant schema privileges
GRANT ALL ON SCHEMA public TO amebo;

-- Grant privileges on existing tables and sequences
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO amebo;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO amebo;

-- Set default privileges for future objects
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO amebo;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO amebo;

-- Verify user exists
\du amebo

-- Success message
SELECT 'Database setup complete!' as status;
