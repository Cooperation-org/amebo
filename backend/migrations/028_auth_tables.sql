-- 028: auth & org-service tables, reconciled from src/db/schema_auth.sql.
--
-- schema_auth.sql was only ever applied by scripts/init_db.py (fresh dev
-- installs); the earnkit deploy runner applies schema.sql + these numbered
-- migrations, so none of these tables existed in a deployed database until
-- api_keys was created by hand on the cohort VM (TODO.md, 2026-07-20). This
-- migration is that file's DDL minus organizations/platform_users, which
-- schema.sql owns — schema_auth.sql's variant of those two tables (extra
-- is_active etc.) was never what deployed databases have.
--
-- Everything is IF NOT EXISTS / DROP-then-CREATE so it applies cleanly both
-- on databases where api_keys was hand-created and on fresh ones.

-- Org <-> Slack-workspace links
CREATE TABLE IF NOT EXISTS org_workspaces (
    id SERIAL PRIMARY KEY,
    org_id INT NOT NULL REFERENCES organizations(org_id) ON DELETE CASCADE,
    workspace_id VARCHAR(20) NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    display_name VARCHAR(255),
    is_primary BOOLEAN DEFAULT false,
    added_by INT REFERENCES platform_users(user_id),
    added_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(org_id, workspace_id)
);

CREATE INDEX IF NOT EXISTS idx_org_workspaces_org ON org_workspaces(org_id);
CREATE INDEX IF NOT EXISTS idx_org_workspaces_workspace ON org_workspaces(workspace_id);
CREATE INDEX IF NOT EXISTS idx_org_workspaces_primary ON org_workspaces(org_id, is_primary) WHERE is_primary = true;

-- Uploaded company documents (policies, handbooks, etc.)
CREATE TABLE IF NOT EXISTS documents (
    document_id SERIAL PRIMARY KEY,
    org_id INT NOT NULL REFERENCES organizations(org_id) ON DELETE CASCADE,
    workspace_id VARCHAR(20) REFERENCES workspaces(workspace_id) ON DELETE SET NULL,
    title VARCHAR(500) NOT NULL,
    file_name VARCHAR(500) NOT NULL,
    file_type VARCHAR(50) NOT NULL,
    file_size_bytes BIGINT,
    file_path TEXT,
    chromadb_collection VARCHAR(255),
    chunk_count INT DEFAULT 0,
    uploaded_by INT NOT NULL REFERENCES platform_users(user_id),
    is_active BOOLEAN DEFAULT true,
    deleted_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_documents_org ON documents(org_id);
CREATE INDEX IF NOT EXISTS idx_documents_workspace ON documents(workspace_id);
CREATE INDEX IF NOT EXISTS idx_documents_active ON documents(org_id, is_active) WHERE is_active = true;
CREATE INDEX IF NOT EXISTS idx_documents_type ON documents(file_type);

-- API keys for programmatic access (service auth: X-API-Key, sha256 hash)
CREATE TABLE IF NOT EXISTS api_keys (
    key_id SERIAL PRIMARY KEY,
    org_id INT NOT NULL REFERENCES organizations(org_id) ON DELETE CASCADE,
    key_name VARCHAR(255) NOT NULL,
    key_hash TEXT NOT NULL,
    key_prefix VARCHAR(20) NOT NULL,
    permissions JSONB DEFAULT '["read"]',
    last_used_at TIMESTAMP,
    expires_at TIMESTAMP,
    is_active BOOLEAN DEFAULT true,
    created_by INT NOT NULL REFERENCES platform_users(user_id),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_keys_org ON api_keys(org_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_api_keys_active ON api_keys(org_id, is_active) WHERE is_active = true;

-- JWT refresh tokens
CREATE TABLE IF NOT EXISTS refresh_tokens (
    token_id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES platform_users(user_id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL,
    device_info JSONB,
    expires_at TIMESTAMP NOT NULL,
    is_revoked BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON refresh_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_hash ON refresh_tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_expires ON refresh_tokens(expires_at) WHERE is_revoked = false;

-- Temporary state tokens for OAuth flows
CREATE TABLE IF NOT EXISTS oauth_states (
    state_id SERIAL PRIMARY KEY,
    state_token VARCHAR(255) UNIQUE NOT NULL,
    user_id INT NOT NULL REFERENCES platform_users(user_id) ON DELETE CASCADE,
    org_id INT NOT NULL REFERENCES organizations(org_id) ON DELETE CASCADE,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_oauth_states_token ON oauth_states(state_token);
CREATE INDEX IF NOT EXISTS idx_oauth_states_expires ON oauth_states(expires_at);

-- Audit trail of important actions
CREATE TABLE IF NOT EXISTS audit_logs (
    log_id SERIAL PRIMARY KEY,
    org_id INT REFERENCES organizations(org_id) ON DELETE CASCADE,
    user_id INT REFERENCES platform_users(user_id) ON DELETE SET NULL,
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(50),
    resource_id VARCHAR(100),
    details JSONB,
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_org ON audit_logs(org_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_user ON audit_logs(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action);
CREATE INDEX IF NOT EXISTS idx_audit_logs_resource ON audit_logs(resource_type, resource_id);

-- Usage tracking for billing/limits
CREATE TABLE IF NOT EXISTS usage_metrics (
    metric_id SERIAL PRIMARY KEY,
    org_id INT NOT NULL REFERENCES organizations(org_id) ON DELETE CASCADE,
    metric_type VARCHAR(50) NOT NULL,
    count INT NOT NULL DEFAULT 0,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(org_id, metric_type, period_start)
);

CREATE INDEX IF NOT EXISTS idx_usage_metrics_org ON usage_metrics(org_id, period_start DESC);
CREATE INDEX IF NOT EXISTS idx_usage_metrics_type ON usage_metrics(metric_type);

-- Password reset flow
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    token_id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES platform_users(user_id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    used_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_hash ON password_reset_tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_user ON password_reset_tokens(user_id);

-- updated_at maintenance, shared by the tables above and schema.sql's
-- organizations/platform_users (which had no such trigger in deployed DBs)
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS update_organizations_updated_at ON organizations;
CREATE TRIGGER update_organizations_updated_at BEFORE UPDATE ON organizations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_platform_users_updated_at ON platform_users;
CREATE TRIGGER update_platform_users_updated_at BEFORE UPDATE ON platform_users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_documents_updated_at ON documents;
CREATE TRIGGER update_documents_updated_at BEFORE UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
