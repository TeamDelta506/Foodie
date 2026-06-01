# role_work.md — Sam Harding (Server-side)

**Week:** 7  
**Role:** Server-side

## Files touched

- `app.py` — Authlib OAuth setup with the GitHub provider; `/login/github` route (initiates flow);
  `/auth/github/callback` route (handles return — three-way create-or-link logic for new users,
  returning GitHub users, and existing local users adding GitHub); defensive field mapping so a
  partial or null GitHub payload never crashes; `/test-login` backdoor (guarded by
  `ENABLE_TEST_LOGIN=1`); `/api/debug/oauth-identity/<username>` endpoint for Playwright
  verification; `ProxyFix` middleware so `SESSION_COOKIE_SECURE` works correctly behind nginx.
- `requirements.txt` — added `Authlib>=1.3.0`, `pytest-playwright>=0.4.0`.
- `tests/e2e/conftest.py` — self-contained fixture: hermetic SQLite DB, embedded Werkzeug
  server on a random port, `ENABLE_TEST_LOGIN=1`, `base_url` override for pytest-playwright.
- `tests/e2e/test_oauth_login_happy_path.py` — server-side Playwright test (see below).

## Playwright test

**File:** `tests/e2e/test_oauth_login_happy_path.py`  
**Function:** `test_oauth_login_happy_path`

The test exercises the full server-side OAuth happy path through a real Chromium browser
without touching GitHub. It starts as an anonymous user, confirms the GitHub login button
is visible on `/login` and points at `/login/github`, then uses the `/test-login` backdoor
to simulate a completed GitHub callback. After login it asserts:

1. The browser lands on `/mealplan` (CONTRACTS.md §3 — success redirect).
2. `"Logged in as"` is visible in the page body.
3. The navbar `.foodie-nav-user` element contains the test username.
4. The `/api/debug/oauth-identity/<username>` API confirms the `github_id` was stored in the
   database (`has_github_identity: true`), verifying the create-or-link logic ran.
5. `/mealplan` is directly accessible (session cookie is live).
6. Logging out returns the navbar to `"Log in"` and removes the username from the page.

A second test (`test_test_login_idempotent`) confirms that calling `/test-login` twice
with the same username reuses the existing `oauth_identities` row rather than creating a
duplicate — verifying the "returning user" branch of the callback logic.

**Week 6 walkthrough adapted:** The core walk (anonymous → login → protected route → logout)
follows the Week 6 server-side walkthrough. The OAuth login step was inserted at the top
using the `/test-login` backdoor instead of username/password, and the `/api/debug/oauth-identity`
assertion was added to verify the Week 7 `github_id` storage requirement.

## Test result

```
tests/e2e/test_oauth_login_happy_path.py::test_oauth_login_happy_path[chromium]      PASSED
tests/e2e/test_oauth_login_happy_path.py::test_test_login_idempotent[chromium]       PASSED
tests/e2e/test_oauth_login_happy_path.py::test_test_login_disabled_without_env[chromium] SKIPPED
2 passed, 1 skipped
```

The skipped test verifies `/test-login` returns 404 when `ENABLE_TEST_LOGIN` is not set;
it is intentionally skipped when the env var is already set in the test session.
