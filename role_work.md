# role_work.md — Justin db-and-security)

**Week:** 7  
**Role:** DB-and-security

## Files touched

- `app.py` — `OAuthIdentity` model, nullable `password_hash`, session cookie flags (`SESSION_COOKIE_HTTPONLY`, `SESSION_COOKIE_SAMESITE`, `SESSION_COOKIE_SECURE`), `PERMANENT_SESSION_LIFETIME`, remember-me cookie settings, `CSRFProtect`, `_upgrade_week7_auth_schema()`
- `scripts/migrate_week7_oauth.sql` — Postgres bridge migration for existing volumes
- `requirements.txt` — `Flask-WTF`
- `templates/base.html`, `templates/login.html`, `templates/register.html`, `templates/mealplan.html`, `templates/recipe_detail.html` — CSRF hidden fields and `X-CSRFToken` on fetch calls
- `tests/csrf_helpers.py` — CSRF token helpers for pytest clients
- `tests/test_db_schema_and_auth.py` — `oauth_identities` schema assertions, `test_csrf_rejects_post_without_token`
- `tests/test_auth.py`, `tests/test_integration.py`, `tests/test_client_recipe_templates.py` — POST/DELETE helpers updated for CSRF
- `tests/e2e/test_protected_page_auth.py` — Playwright protected-page auth gate
- `e2e/db_security.md` — step 8 browser walk status (Playwright coverage)

## Playwright test

**File:** `tests/e2e/test_protected_page_auth.py`  
**Function:** `test_mealplan_protected_before_login_after_logout`

**What it verifies:** In a real Chromium session, `/mealplan` shows the login page (not the weekly planner grid) when the user is logged out; after registering through the UI the same route renders the “Weekly meal plan” heading and seven `[data-day]` slots with the username in the navbar; after clicking **Log out** the navbar returns to **Log in** and a second visit to `/mealplan` again shows only the login form with no planner content. This exercises Flask-Login’s `@login_required` gate through rendered DOM, not HTTP status codes alone.

**Week 6 walkthrough adapted:** `e2e/db_security.md` step 8 (auth flow browser walk — register, `/mealplan` while logged in, logout, `/mealplan` while logged out).
**Week 6 walkthrough adapted:** None — new minimal smoke path focused on login-page entry only.

## Known gaps

- EC2 instance disk full — `playwright install chromium` fails locally with ENOSPC; e2e smoke test runs in GitHub Actions CI instead.

- Real GitHub OAuth still requires `OAUTH_CLIENT_ID` / `OAUTH_CLIENT_SECRET` in `.env` for manual runs; Playwright uses `/test-login`.
- Full-stack lifecycle and per-role e2e suites live under `tests/e2e/`; see `team_walkthrough.md`.
