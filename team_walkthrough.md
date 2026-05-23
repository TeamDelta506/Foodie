# Team Walkthrough — Week 7 Full-System E2E Suite

**Suite file:** `tests/e2e/test_full_lifecycle.py`  
**Run command:**
```
ENABLE_TEST_LOGIN=1 pytest tests/e2e/test_full_lifecycle.py -v
```

This document explains what each test in the full-lifecycle suite actually
verifies and what user-visible regression it would catch. A new teammate should
be able to understand the team's e2e coverage and its honest limits in about
ten minutes.

---

## Background: the test-login backdoor

Every test in this suite (and in the per-role suites) relies on
`GET /test-login?username=<handle>`, an endpoint that only exists when the
server is started with `ENABLE_TEST_LOGIN=1`. It bypasses GitHub's OAuth
redirect entirely: it creates or retrieves a User row, marks the Flask-Login
session as active, and redirects to the home page — exactly what
`/auth/github/callback` does after a successful GitHub authorisation. Without
this backdoor, automated tests would need a real GitHub account and would be
blocked by browser-based MFA and rate limits.

The backdoor also sets `session.permanent = True` and records a synthetic
`github_id` of the form `test_<username>`, so the create-or-link logic in the
callback is exercisable end-to-end without real GitHub credentials.

---

## Scenario 1 — First-time OAuth login

**Test:** `test_first_time_oauth_login`

A user who has never visited Foodie before clicks "Continue with GitHub" on the
login page, authorises the app, and lands on the home page for the first time.

**What the test does:**  
It first asks the debug endpoint (`/api/debug/oauth-identity/<username>`) to
confirm the account does not yet exist (404 response). It then hits
`/test-login?username=lifecycle_<timestamp>` to simulate a completed GitHub
callback. After the redirect to `/`, it checks three things:

1. The username appears somewhere in the page body (flash message confirms
   "Logged in as …").
2. The debug endpoint now returns `has_github_identity: true` with a
   `github_id` matching the synthetic value written by the backdoor. This is
   the "row in the oauth_identity store" check — our implementation stores
   `github_id` on the User row rather than in a separate table, so the debug
   endpoint is the portable way to inspect it from a Playwright context.
3. Navigating to `/mealplan` succeeds (status 200, seven `data-day` slots
   rendered), confirming the session is live and the auth gate does not block
   the user immediately after login.

**Regression caught:**  
If the create-or-link branch in `/auth/github/callback` forgot to commit the
`github_id` field after building the new User row (e.g. missing `db.commit()`
or `github_id` was left `None`), the debug endpoint would return
`has_github_identity: false`. This would also cause scenario 2 to fail:
without a stored `github_id`, the second login would find no existing identity
and create a second User row, silently orphaning the first account's data.

---

## Scenario 2 — Returning OAuth login (row reused, not duplicated)

**Test:** `test_returning_oauth_login_reuses_row`

The same user from scenario 1 logs out and clicks "Continue with GitHub" again.
The existing account should be found by its `github_id` and logged in directly —
no new row should be inserted.

**What the test does:**  
After logging out, it reads the `github_id` from the debug endpoint and stores
it. It then calls `/test-login?username=<same handle>` again. If the
create-or-link logic is correct, `test-login` finds the existing User by
username (which has the same `github_id` as before) and logs in the existing
account. The test then verifies:

1. The `github_id` in the debug endpoint is unchanged from before the second
   login.
2. A second account (`lifecycle_<timestamp>_1`) does not exist — it hits the
   debug endpoint for that derived name and asserts 404.
3. The user lands on the home page with their original username in the navbar.

**Regression caught:**  
If the callback always executed `INSERT` without first querying for an existing
`github_id` match, each GitHub login would create a fresh account with a
numeric suffix (`_1`, `_2`, …). The user would log in to a different empty
account every time, losing all meal plans and scaling history saved under the
original account. This test catches that exact branch error: the duplicate
identity check (`db.exec(select(User).where(User.github_id == github_id))`)
must run before any `INSERT`.

---

## Scenario 3 — CSRF protection: tokenless POST is rejected

**Test:** `test_csrf_protection_rejects_unauthenticated_post`

A request to a state-changing endpoint (`POST /mealplan`) that arrives with no
valid session cookie must be rejected — the server must not modify any user's
data based on a request with no authenticated identity.

**What the test does:**  
It uses `playwright.request.new_context()` to create a fresh
`APIRequestContext` — a bare HTTP client with no browser session cookies
associated with any logged-in user. It sends a POST to `/mealplan` with valid
form fields (`day_of_week=1`, `recipe_id=1`, `servings=2`). Because Playwright
follows redirects by default, the response URL after the full redirect chain
must contain `/login`, confirming the endpoint refused the request and sent the
client to authenticate first.

This is not a CSRF-token check in the WTForms sense (the app does not currently
use Flask-WTF tokens). It is instead a test that the authentication gate —
Flask-Login's `@login_required` on the POST handler — is in place. Without a
valid session cookie, there is no authenticated user for the endpoint to write
on behalf of, so the POST must be turned away.

**Regression caught:**  
If the `@login_required` decorator were accidentally removed from the
`POST /mealplan` handler (e.g. during a refactor that moved the decorator to
the wrong function), any request from any origin could modify any user's meal
plan by simply guessing their `recipe_id` and `day_of_week`. This test catches
that deletion: the fresh API context has no session, and if the handler accepts
the POST anyway, the response URL will be `/mealplan` (not `/login`), and the
assertion will fail.

---

## Scenario 4 — Session expiry blocks the protected route

**Test:** `test_session_expiry_blocks_protected_route`

Once a user's session is no longer valid — whether because the session cookie
expired or was cleared by the browser — the protected `/mealplan` route must
redirect to `/login`. The user is not remembered indefinitely.

**What the test does:**  
It logs in a fresh test user via the backdoor and confirms `/mealplan` is
accessible (7 `data-day` slots visible). It then calls
`page.context.clear_cookies()` to erase all cookies in the browser context,
simulating what happens when a session cookie reaches its `Expires` date and
the browser discards it. It then navigates to `/mealplan` again and asserts
the response URL contains `/login` and the navbar shows the "Log in" link
(anonymous state).

**Regression caught:**  
If Flask-Login's session validation were replaced by a weaker check that only
reads a plain, unsigned cookie (e.g. `session.get("user_id")` without verifying
the HMAC signature), an attacker could forge a session by crafting any cookie
with their target's `user_id`. Clearing the legitimate cookie would still be
required to reproduce this test, but the test itself documents the contract:
without a valid, signed session cookie, access to `/mealplan` must be denied.
It would also catch a regression where `@login_required` was accidentally
swapped for a custom guard that cached the result beyond the session lifetime.

---

## Gaps — what this suite does not cover

**We do not drive the actual GitHub OAuth redirect.** Every test uses the
`/test-login` backdoor in place of the real authorise → callback round-trip.
This means we do not test Authlib's `authorize_redirect()` call, the PKCE
state-parameter validation, GitHub's token exchange, or the raw profile JSON
parsing inside `/auth/github/callback`. A regression in any of those layers
would not be caught by this suite. Driving the real flow requires a live GitHub
OAuth App, browser interaction with github.com (including MFA), and secrets in
CI — all of which are out of scope for this week's lab.

**We do not test the link-existing-local-user path.** The create-or-link logic
has three branches: new user, returning GitHub user, and a logged-in local user
adding GitHub to their account. Scenario 1 covers the first branch, scenario 2
covers the second. The third branch (a user who registered with a password logs
in via GitHub to link their account) is not exercised. Adding it would require
creating a password-based account first, then calling the backdoor while that
session is active.

**We do not test concurrent logins or race conditions.** If two requests arrive
simultaneously for a new `github_id`, a naive implementation without a database
unique constraint could insert two rows. The unique index on `github_id` in the
schema prevents this at the DB level, but no test exercises the concurrent path.

**We do not test the Remember me long-lived cookie.** Verifying a 30-day cookie
would require advancing the system clock by 30 days inside the test, which is
not reliable without a time-control shim. The `REMEMBER_COOKIE_DURATION` config
is set correctly in code; the test in `test_client_side_login.py` only confirms
the checkbox is present and the form submits without error.

**We do not test cross-browser behaviour.** All tests run on Chromium. Firefox
and WebKit have subtly different cookie and redirect handling; a bug that only
appears in one engine would not be caught.

**We do not test the actual GitHub profile field mapping.** The callback
defensively handles null `login`, null `name`, null `id`, and so on. Unit tests
in `tests/test_integration.py` mock Authlib to cover those branches; the
Playwright suite cannot easily inject a malformed GitHub payload without also
mocking the network at the server level.

---

## Running the full suite

```powershell
# 1. Install dependencies (one-time)
pip install Authlib pytest-playwright
py -m playwright install chromium

# 2. Start the app with SQLite (no Docker needed)
$env:DATABASE_URL = "sqlite:///./foodie_dev.db"
$env:ENABLE_TEST_LOGIN = "1"
$env:SECRET_KEY = "dev-secret"
py app.py          # leave this terminal open

# 3. In a second terminal, run the suite
$env:ENABLE_TEST_LOGIN = "1"
py -m pytest tests/e2e/test_full_lifecycle.py -v
```

To run all three e2e suites together (per-role + full-system):
```powershell
$env:ENABLE_TEST_LOGIN = "1"
py -m pytest tests/e2e/ -v
```

Expected output: **10 passed, 1 skipped** (the guard test skips when
`ENABLE_TEST_LOGIN=1`, which is the correct behaviour in a dev/CI context).
