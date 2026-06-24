-- Seed: LinkedTrust (org_id 1) team provisioning — configurable tools + the
-- confirmed Taiga account map from the 2026-06-24 access grant.
--
-- Idempotent (ON CONFLICT DO NOTHING against migration 019's unique indexes).
-- Org-specific seed data, safe to re-run. Roster rows in platform_users are
-- NOT seeded here — those are populated with VERIFIED identity by the LT-SSO
-- invite flow; member_tool_accounts.user_id is backfilled then.

-- 1. Configurable tools for org 1. Secret resolved via
--    CredentialResolver(org_id=1, kind, cred_label) — not stored here.
INSERT INTO org_tools (org_id, tool_key, kind, cred_label, display_name, base_url, default_role, config)
VALUES
  (1, 'taiga',    'taiga', 'default', 'Taiga / Marten', 'https://taiga.linkedtrust.us', 'Back',            '{"cli":"mcp-taiga"}'),
  (1, 'odoo_crm', 'odoo',  'default', 'LinkedTrust CRM', 'https://crm.linkedtrust.us',  'internal+sales',  '{"cli":"odoo-cli"}')
ON CONFLICT (org_id, tool_key) DO NOTHING;

-- 2. Confirmed Taiga accounts (VM user in the comment; external_id = Taiga user id).
--    state='linked' = role granted on 2026-06-24; myee='failed' (Taiga rejected:
--    "user must be a valid contact" — stale account, not linked to the inviter).
INSERT INTO member_tool_accounts
  (org_id, tool_key, external_id, external_username, granted_role, state, reason, last_synced_at)
VALUES
  (1, 'taiga', '333', 'AgnesKoinange',  'Back', 'linked', NULL, NOW()),  -- agnes
  (1, 'taiga', '352', 'Kene',           'Back', 'linked', NULL, NOW()),  -- kene
  (1, 'taiga', '407', 'Marwan',         'Back', 'linked', NULL, NOW()),  -- marwan
  (1, 'taiga', '159', 'Gitonga',        'Back', 'linked', NULL, NOW()),  -- gitonga / mgitonga
  (1, 'taiga', '251', 'rishabh',        'Back', 'linked', NULL, NOW()),  -- rishabh
  (1, 'taiga', '369', 'AmosMwangi',     'Back', 'linked', NULL, NOW()),  -- amos
  (1, 'taiga', '350', 'AmrNabel',       'Back', 'linked', NULL, NOW()),  -- amr
  (1, 'taiga', '402', 'ArtworxAI',      'Back', 'linked', NULL, NOW()),  -- dana (Dana W. Martinez)
  (1, 'taiga', '389', 'MokaAhmed',      'Back', 'linked', NULL, NOW()),  -- moka
  (1, 'taiga', '368', 'Molly',          'Back', 'linked', NULL, NOW()),  -- molly (Ahlam Sayed)
  (1, 'taiga', '344', 'ZakiaMangal',    'Back', 'linked', NULL, NOW()),  -- zakia (Zakia Mangal == Zakia Imran)
  (1, 'taiga', '435', 'goldavelez_org', 'Back', 'linked', NULL, NOW()),  -- golda (chosen primary)
  (1, 'taiga', '329', 'AniPeter',       'Back', 'linked', NULL, NOW()),  -- peter (more perms: 16 vs 3)
  (1, 'taiga', '320', 'SIA',            'Back', 'linked', NULL, NOW()),  -- sia (11 vs 0)
  (1, 'taiga', '297', 'tuna7',          'Back', 'linked', NULL, NOW()),  -- tuna (== Thura Aung, 18 vs 0)
  (1, 'taiga', '18',  'myee',           'Back', 'failed', 'Taiga: user must be a valid contact (stale account #18, myee@yahoo.com, not linked to inviter)', NOW())  -- myee
ON CONFLICT (org_id, tool_key, external_id) WHERE external_id IS NOT NULL DO NOTHING;
