-- ============================================================================
-- AUTHENTICATION & USER MANAGEMENT SCHEMA
-- Organizations, Users, API Keys for the SaaS platform
-- ============================================================================

-- 1. ORGANIZATIONS: Companies using the platform
CREATE TABLE IF NOT EXISTS organizations (
    org_id SERIAL PRIMARY KEY,
    org_name VARCHAR(255) NOT NULL,
    org_slug VARCHAR(100) UNIQUE NOT NULL, -- URL-friendly name
    email_domain VARCHAR(255), -- For automatic user invitation
    subscription_plan VARCHAR(50) DEFAULT 'free', -- 'free', 'starter', 'pro', 'enterprise'
    subscription_status VARCHAR(50) DEFAULT 'active', -- 'active', 'trialing', 'past_due', 'canceled'
    trial_ends_at TIMESTAMP,
    max_workspaces INT DEFAULT 1, -- Plan limit
    max_users INT DEFAULT 5, -- Plan limit
    max_documents INT DEFAULT 10, -- Plan limit
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_organizations_slug ON organizations(org_slug);
CREATE INDEX idx_organizations_active ON organizations(is_active) WHERE is_active = true;

-- ============================================================================

-- 2. USERS: Platform users (org admins, members)
CREATE TABLE IF NOT EXISTS platform_users (
    user_id SERIAL PRIMARY KEY,
    org_id INT NOT NULL REFERENCES organizations(org_id) ON DELETE CASCADE,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL, -- bcrypt hash
    full_name VARCHAR(255),
    role VARCHAR(50) DEFAULT 'member', -- 'owner', 'admin', 'member', 'viewer'
    is_active BOOLEAN DEFAULT true,
    email_verified BOOLEAN DEFAULT false,
    last_login_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_platform_users_org ON platform_users(org_id);
CREATE INDEX idx_platform_users_email ON platform_users(email);
CREATE INDEX idx_platform_users_role ON platform_users(org_id, role);

-- ============================================================================

-- 3. ORG_WORKSPACES: Link organizations to Slack workspaces
CREATE TABLE IF NOT EXISTS org_workspaces (
    id SERIAL PRIMARY KEY,
    org_id INT NOT NULL REFERENCES organizations(org_id) ON DELETE CASCADE,
    workspace_id VARCHAR(20) NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    display_name VARCHAR(255), -- Custom name for this workspace
    is_primary BOOLEAN DEFAULT false, -- Primary workspace for org
    added_by INT REFERENCES platform_users(user_id),
    added_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(org_id, workspace_id)
);

CREATE INDEX idx_org_workspaces_org ON org_workspaces(org_id);
CREATE INDEX idx_org_workspaces_workspace ON org_workspaces(workspace_id);
CREATE INDEX idx_org_workspaces_primary ON org_workspaces(org_id, is_primary) WHERE is_primary = true;

-- ============================================================================

-- 4. DOCUMENTS: Uploaded company documents (policies, handbooks, etc.)
CREATE TABLE IF NOT EXISTS documents (
    document_id SERIAL PRIMARY KEY,
    org_id INT NOT NULL REFERENCES organizations(org_id) ON DELETE CASCADE,
    workspace_id VARCHAR(20) REFERENCES workspaces(workspace_id) ON DELETE SET NULL, -- Optional workspace link
    title VARCHAR(500) NOT NULL,
    file_name VARCHAR(500) NOT NULL,
    file_type VARCHAR(50) NOT NULL, -- 'pdf', 'docx', 'txt', 'md'
    file_size_bytes BIGINT,
    file_path TEXT, -- S3/local storage path
    chromadb_collection VARCHAR(255), -- ChromaDB collection name
    chunk_count INT DEFAULT 0, -- Number of chunks in ChromaDB
    uploaded_by INT NOT NULL REFERENCES platform_users(user_id),
    is_active BOOLEAN DEFAULT true, -- Can be deactivated without deletion
    deleted_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_documents_org ON documents(org_id);
CREATE INDEX idx_documents_workspace ON documents(workspace_id);
CREATE INDEX idx_documents_active ON documents(org_id, is_active) WHERE is_active = true;
CREATE INDEX idx_documents_type ON documents(file_type);

-- ============================================================================

-- 5. API_KEYS: API keys for programmatic access
CREATE TABLE IF NOT EXISTS api_keys (
    key_id SERIAL PRIMARY KEY,
    org_id INT NOT NULL REFERENCES organizations(org_id) ON DELETE CASCADE,
    key_name VARCHAR(255) NOT NULL, -- User-friendly name
    key_hash TEXT NOT NULL, -- Hashed API key
    key_prefix VARCHAR(20) NOT NULL, -- First few chars for display (sk_live_abc...)
    permissions JSONB DEFAULT '["read"]', -- ['read', 'write', 'admin']
    last_used_at TIMESTAMP,
    expires_at TIMESTAMP,
    is_active BOOLEAN DEFAULT true,
    created_by INT NOT NULL REFERENCES platform_users(user_id),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_api_keys_org ON api_keys(org_id);
CREATE INDEX idx_api_keys_hash ON api_keys(key_hash);
CREATE INDEX idx_api_keys_active ON api_keys(org_id, is_active) WHERE is_active = true;

-- ============================================================================

-- 6. REFRESH_TOKENS: JWT refresh tokens for auth
CREATE TABLE IF NOT EXISTS refresh_tokens (
    token_id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES platform_users(user_id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL,
    device_info JSONB, -- User agent, IP, etc.
    expires_at TIMESTAMP NOT NULL,
    is_revoked BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_refresh_tokens_user ON refresh_tokens(user_id);
CREATE INDEX idx_refresh_tokens_hash ON refresh_tokens(token_hash);
CREATE INDEX idx_refresh_tokens_expires ON refresh_tokens(expires_at) WHERE is_revoked = false;

-- ============================================================================

-- 6b. OAUTH_STATES: Temporary state tokens for OAuth flows
CREATE TABLE IF NOT EXISTS oauth_states (
    state_id SERIAL PRIMARY KEY,
    state_token VARCHAR(255) UNIQUE NOT NULL,
    user_id INT NOT NULL REFERENCES platform_users(user_id) ON DELETE CASCADE,
    org_id INT NOT NULL REFERENCES organizations(org_id) ON DELETE CASCADE,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_oauth_states_token ON oauth_states(state_token);
CREATE INDEX idx_oauth_states_expires ON oauth_states(expires_at);

-- ============================================================================

-- 7. AUDIT_LOGS: Track important actions
CREATE TABLE IF NOT EXISTS audit_logs (
    log_id SERIAL PRIMARY KEY,
    org_id INT REFERENCES organizations(org_id) ON DELETE CASCADE,
    user_id INT REFERENCES platform_users(user_id) ON DELETE SET NULL,
    action VARCHAR(100) NOT NULL, -- 'user_created', 'document_uploaded', 'workspace_connected', etc.
    resource_type VARCHAR(50), -- 'user', 'document', 'workspace', etc.
    resource_id VARCHAR(100), -- ID of affected resource
    details JSONB, -- Additional context
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_audit_logs_org ON audit_logs(org_id, created_at DESC);
CREATE INDEX idx_audit_logs_user ON audit_logs(user_id, created_at DESC);
CREATE INDEX idx_audit_logs_action ON audit_logs(action);
CREATE INDEX idx_audit_logs_resource ON audit_logs(resource_type, resource_id);

-- ============================================================================

-- 8. USAGE_METRICS: Track usage for billing/limits
CREATE TABLE IF NOT EXISTS usage_metrics (
    metric_id SERIAL PRIMARY KEY,
    org_id INT NOT NULL REFERENCES organizations(org_id) ON DELETE CASCADE,
    metric_type VARCHAR(50) NOT NULL, -- 'queries', 'documents', 'messages', 'api_calls'
    count INT NOT NULL DEFAULT 0,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(org_id, metric_type, period_start)
);

CREATE INDEX idx_usage_metrics_org ON usage_metrics(org_id, period_start DESC);
CREATE INDEX idx_usage_metrics_type ON usage_metrics(metric_type);

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply to relevant tables
CREATE TRIGGER update_organizations_updated_at BEFORE UPDATE ON organizations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_platform_users_updated_at BEFORE UPDATE ON platform_users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_documents_updated_at BEFORE UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- DEFAULT DATA
-- ============================================================================

-- Insert default organization for testing
INSERT INTO organizations (org_name, org_slug, subscription_plan, subscription_status)
VALUES ('Default Organization', 'default', 'free', 'active')
ON CONFLICT DO NOTHING;
