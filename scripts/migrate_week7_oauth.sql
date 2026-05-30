-- Week 7 auth schema patch for existing Postgres volumes (CONTRACTS.md §1).
-- Formal migration: Justin (db-and-security). Bridge until Alembic lands.
--
-- Run if login/OAuth fails on github_id or password_hash errors:
--   docker compose exec db psql -U app -d app -f - < scripts/migrate_week7_oauth.sql
-- Or restart the app — app.py applies the same changes on startup.

-- OAuth-only accounts (GitHub / test-login backdoor) have no local password.
ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL;

ALTER TABLE users ADD COLUMN IF NOT EXISTS github_id VARCHAR(64);
ALTER TABLE users ADD COLUMN IF NOT EXISTS github_login VARCHAR(255);
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_github_id ON users (github_id) WHERE github_id IS NOT NULL;

-- Week 5 volumes: created_at NOT NULL without a default breaks OAuth user create.
ALTER TABLE users ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP;

-- oauth_identities is created by SQLModel.metadata.create_all on app startup.
