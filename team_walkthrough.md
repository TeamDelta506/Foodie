# Team Walkthrough — Week 7 Full-System E2E Suite

**Suite file:** `tests/e2e/test_full_lifecycle.py`  
**Run command:**

```powershell
$env:ENABLE_TEST_LOGIN = "1"
py -m pytest tests/e2e/test_full_lifecycle.py -v
```

This document is the map for our end-to-end coverage: what a user would see in the browser, what each test actually checks in the database and HTTP layer, and what regression each test is designed to catch. Read it once before touching OAuth or session code; it should take about ten minutes.

---

## How the pieces fit together

Foodie’s Week 7 work spans four roles. **Sam** owns GitHub OAuth routes, the create-or-link algorithm, and the `oauth_identities` table. **Asia** owns login/register templates, the navbar, Remember me, and client-side form behavior. **Justin** owns schema (`oauth_identities`, nullable `password_hash`), session cookie policy, and Flask-WTF CSRF on every state-changing HTML form. **Sowmya (coordinator)** owns `CONTRACTS.md`, the threaded e2e server in `tests/e2e/conftest.py`, the `/test-login` backdoor, and the full-lifecycle suite in `test_full_lifecycle.py`.

Per-role Playwright tests live beside the lifecycle file: Sam’s happy-path OAuth test, Asia’s navbar test, Justin’s protected-page gate test, and the coordinator smoke test on the login page. Together they prove each lane shipped; the lifecycle file proves the lanes **integrate** as one user journey.

Every automated OAuth test uses the **test-login backdoor** instead of `github.com`. That is intentional: we still exercise the same post-callback outcomes (user row, `oauth_identities` row, Flask-Login session, redirect to `/mealplan`), but we do not depend on a live GitHub app, MFA, or CI secrets for the authorize redirect.

---

## Background: the test-login backdoor

When the server starts with `ENABLE_TEST_LOGIN=1`, `GET /test-login?username=<handle>` is available. It mirrors what `/auth/github/callback` does after a successful authorization: find or create a `users` row, ensure an `oauth_identities` row with `provider='github'` and `provider_user_id='test_<handle>'`, set `session.permanent = True`, call `login_user`, flash `Logged in as <username>`, and redirect to `/mealplan`.

The debug route `GET /api/debug/oauth-identity/<username>` (same env guard) returns JSON so Playwright can assert on the database without opening SQL. It reports `has_github_identity` and `provider_user_id` from `oauth_identities`, not from legacy `users.github_id` alone.

---

## Scenario 1 — First-time OAuth login

**Test:** `test_first_time_oauth_login`

**User-visible behavior:** Someone with no Foodie account clicks “Continue with GitHub” (simulated by the backdoor), lands on the weekly meal plan, and sees their username in the navbar and flash area.

**What the test does:** It confirms the account does not exist yet (`404` from the debug endpoint), then hits `/test-login?username=lifecycle_<timestamp>`. After redirect it checks: URL is `/mealplan`, username appears in the nav, the debug endpoint shows `has_github_identity: true` with `provider_user_id` equal to `test_<username>`, and seven `[data-day]` slots render (protected route is open). The user stays logged in until scenario 2 logs them out.

**Regression caught:** If the create-or-link path forgot to insert into `oauth_identities` (for example missing `db.commit()` after `_link_github_identity`), the debug endpoint would return `has_github_identity: false`. Scenario 2 would then fail in a subtler way: the second login might create a duplicate user instead of reusing the same GitHub identity, orphaning meal-plan data from the first account.

---

## Scenario 2 — Returning OAuth login (row reused, not duplicated)

**Test:** `test_returning_oauth_login_reuses_row`

**User-visible behavior:** The same person logs out and signs in with GitHub again. They should see the same username and the same account data—not a fresh empty account with a numeric suffix.

**What the test does:** After ensuring logout, it records `provider_user_id` from the debug endpoint, runs `/test-login` again with the same username, and asserts the identity value is unchanged. It also checks that `lifecycle_<timestamp>_1` does not exist (`404`), proving no duplicate user was created for a second login.

**Regression caught:** If the callback always ran `INSERT` without first looking up `oauth_identities` by `provider_user_id`, each login would create a new user (`lifecycle_XYZ_1`, `_2`, …). The user would lose meal plans and scaling history tied to the first row. This test fails exactly when that lookup-before-insert branch is broken.

---

## Scenario 3 — CSRF protection: tokenless POST is rejected

**Test:** `test_csrf_protection_rejects_tokenless_post`

**User-visible behavior:** A logged-in user’s browser only accepts meal-plan changes when the form includes a valid CSRF token. A cross-site forged POST without that token must not change data.

**What the test does:** Playwright’s `request.new_context()` establishes a session via `/test-login`, then sends `POST /mealplan` with valid `day_of_week`, `recipe_id`, and `servings` but **no** `csrf_token`. Flask-WTF must answer **`400`**, not `302` to `/mealplan`.

**Regression caught:** If `CSRFProtect` were removed or the mealplan template dropped the hidden `csrf_token` field, any site could POST on behalf of a logged-in user. An auth-only check (`@login_required` without CSRF) would not catch that—this test requires both session **and** token.

---

## Scenario 4 — Session expiry blocks the protected route

**Test:** `test_session_expiry_blocks_protected_route`

**User-visible behavior:** After the session lifetime passes, opening “Meal plan” sends the user back to login instead of showing the planner.

**What the test does:** It temporarily sets `PERMANENT_SESSION_LIFETIME` to two seconds on the running app, logs in via the backdoor, confirms `/mealplan` works, waits 2.5 seconds, then navigates to `/mealplan` again. The URL must contain `/login` and the navbar must show “Log in”.

**Regression caught:** If `session.permanent` were not set on login, or lifetime were misconfigured, users would stay authenticated far longer than policy allows. Clearing cookies manually would not catch a bug where the server never set cookie expiry—this test exercises real time-based expiry.

For local runs with a short lifetime only in tests, set `SESSION_LIFETIME_SECONDS=2` in the environment when starting the app; the e2e test patches the same config on the live server instance.

---

## Gaps — what this suite does not cover

**We do not drive the actual GitHub OAuth redirect.** The `/test-login` backdoor stands in for everything after `authorize_redirect`. Authlib’s redirect, PKCE/state validation, token exchange, and raw profile parsing in `/auth/github/callback` are covered by unit tests in `tests/test_integration.py` with mocks, not by Playwright against `github.com`.

**We do not test linking GitHub to an existing password account.** Create-or-link has three branches: new user (scenario 1), returning GitHub user (scenario 2), and “already logged in locally, add GitHub.” The third branch needs a password registration step plus backdoor while that session is active.

**We do not test concurrent first-time logins for the same `provider_user_id`.** The unique constraint on `(provider, provider_user_id)` prevents duplicate rows at the DB level; no test hammers two simultaneous callbacks.

**We do not test Remember-me for 30 days.** That would require advancing the clock by weeks; we only verify the checkbox exists and password/OAuth flows accept `remember=y` in role-level tests.

**We do not test cross-browser engines.** CI and local e2e use Chromium only; cookie or redirect quirks in Firefox/WebKit are out of scope.

**We do not inject malformed GitHub JSON in Playwright.** Null `login`, missing `id`, and similar cases are mocked in server integration tests, not in the browser suite.

---

## Running the full suite

```powershell
# 1. Install dependencies (one-time)
pip install -r requirements.txt
py -m playwright install chromium

# 2. Start the app (SQLite is enough for local e2e)
$env:DATABASE_URL = "sqlite:///./foodie_dev.db"
$env:ENABLE_TEST_LOGIN = "1"
$env:SECRET_KEY = "dev-secret"
py app.py

# 3. Second terminal — lifecycle + all e2e
$env:ENABLE_TEST_LOGIN = "1"
py -m pytest tests/e2e/ -v
```

With only the in-process live server (recommended), step 2 is optional—the e2e `conftest.py` starts its own app on a random port.

**Expected counts:** 45 tests collected — **44 passed, 1 skipped** (`test_test_login_disabled_without_env` skips when `ENABLE_TEST_LOGIN=1`, which is correct for dev and CI).

---

## Frontend and database alignment

Templates and scripts match the Week 7 schema and contracts:

- **OAuth entry:** Login and register pages link to `/login/github`; `forms.js` appends `remember=y` when the checkbox is checked.
- **Navbar:** `Logged in as {username}` when `user` is set; logout is a POST form with CSRF token.
- **Meal plan:** POST form includes `csrf_token`; “Clear day” sends `X-CSRFToken` from the meta tag for `DELETE /mealplan/<day>`.
- **Identity storage:** GitHub identities live in `oauth_identities`; legacy `users.github_id` is kept in sync for older code paths.

If UI changes drop hidden CSRF fields or stop sending the header on DELETE, role tests and scenario 3 fail before bad data reaches production.
