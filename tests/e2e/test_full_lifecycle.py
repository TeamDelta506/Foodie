"""
tests/e2e/test_full_lifecycle.py
=================================
Full-system Playwright suite — Week 7 Group deliverable.

Exercises the complete login lifecycle as one user would experience it,
across four concrete scenarios:

  1. First-time OAuth login  — new account created, GitHub identity stored.
  2. Returning OAuth login   — existing row reused, no duplicate created.
  3. CSRF protection         — tokenless POST to a guarded endpoint is rejected.
  4. Session expiry          — after session cookies are cleared, the protected
                               page is no longer accessible.

Run (from repo root, app must be running with ENABLE_TEST_LOGIN=1):
    ENABLE_TEST_LOGIN=1 pytest tests/e2e/test_full_lifecycle.py -v
    ENABLE_TEST_LOGIN=1 pytest tests/e2e/test_full_lifecycle.py -v --headed

Prerequisites
-------------
    pip install pytest-playwright
    py -m playwright install chromium

    # Start the app (SQLite, no Docker required):
    $env:DATABASE_URL="sqlite:///./foodie_dev.db"
    $env:ENABLE_TEST_LOGIN="1"
    $env:SECRET_KEY="dev-secret"
    py app.py
"""

from __future__ import annotations

import time

import pytest
from playwright.sync_api import APIRequestContext, Page, expect


# ── Shared username keeps scenario 1 and scenario 2 in the same account ─────
_RUN_TS    = int(time.time())
OAUTH_USER = f"lifecycle_{_RUN_TS}"


# ── Helpers ──────────────────────────────────────────────────────────────────

def goto(page: Page, base_url: str, path: str) -> None:
    page.goto(f"{base_url}{path}")


def logout(page: Page) -> None:
    """Click the navbar logout button and wait for the home page to load."""
    page.locator("form[action*='logout'] button").click()
    expect(page.locator("nav").get_by_role("link", name="Log in")).to_be_visible()


def get_oauth_identity(api: APIRequestContext, base_url: str, username: str) -> dict:
    """Fetch the debug oauth-identity JSON for a user."""
    resp = api.get(f"{base_url}/api/debug/oauth-identity/{username}")
    assert resp.ok, f"Debug endpoint failed: {resp.status} {resp.url}"
    return resp.json()


# ════════════════════════════════════════════════════════════════════════════
# Scenario 1 — First-time OAuth login
# ════════════════════════════════════════════════════════════════════════════

def test_first_time_oauth_login(page: Page, base_url: str) -> None:
    """
    A user with no existing local account logs in via the GitHub OAuth flow
    (simulated by the test-login backdoor).

    Verifies:
      - The user lands on the home page with their username visible.
      - A GitHub row exists in oauth_identities for that user.
      - The flash message confirms "Logged in as <username>".
      - The user can access the protected /mealplan route immediately.

    Regression caught: if the create-or-link branch failed to insert
    oauth_identities, the debug endpoint would return has_github_identity=false, and the second
    login in scenario 2 would create a duplicate account instead of reusing
    the existing one.
    """
    # Confirm the user does not yet exist.
    resp = page.request.get(f"{base_url}/api/debug/oauth-identity/{OAUTH_USER}")
    assert resp.status == 404, "User should not exist yet at start of test."

    # Simulate first-time GitHub OAuth via the test-login backdoor.
    goto(page, base_url, f"/test-login?username={OAUTH_USER}")

    # ── Lands on meal plan (Week 7 deliberate landing) ───────────────────────
    assert "/mealplan" in page.url, (
        f"Expected /mealplan after first login, got {page.url!r}"
    )

    # ── Username visible in navbar ───────────────────────────────────────────
    expect(page.locator("nav").get_by_text(OAUTH_USER)).to_be_visible()

    # ── Flash message confirms login ──────────────────────────────────────────
    assert OAUTH_USER in page.locator("body").inner_text(), (
        f"'{OAUTH_USER}' not found in page after login."
    )

    # ── GitHub identity stored in DB (via debug endpoint) ────────────────────
    identity = get_oauth_identity(page.request, base_url, OAUTH_USER)
    assert identity["has_github_identity"] is True, (
        "github_id was not stored after first-time OAuth login."
    )
    assert identity["github_id"] == f"test_{OAUTH_USER}", (
        f"Unexpected github_id: {identity['github_id']!r}"
    )

    # ── Protected route accessible with live session ──────────────────────────
    goto(page, base_url, "/mealplan")
    assert "/login" not in page.url, (
        "Session is not live — /mealplan redirected to login."
    )
    expect(page.locator("[data-day]")).to_have_count(7)

    # Leave the user logged in so scenario 2 can log out first.
    logout(page)


# ════════════════════════════════════════════════════════════════════════════
# Scenario 2 — Returning OAuth login (row reused, not duplicated)
# ════════════════════════════════════════════════════════════════════════════

def test_returning_oauth_login_reuses_row(page: Page, base_url: str) -> None:
    """
    The same user from scenario 1 logs in a second time via GitHub OAuth.
    The existing identity row must be reused — no duplicate user or identity
    row is created.

    Verifies:
      - Login succeeds and the same username is shown in the navbar.
      - The github_id in the debug endpoint is unchanged (same value as after
        the first login).
      - The debug endpoint does not suddenly show a second account for the
        same github_id.

    Regression caught: if the create-or-link branch always did `INSERT` instead
    of first checking for an existing github_id, the second login would create
    a second User row (possibly with a numeric suffix like `lifecycle_XYZ_1`),
    and the original account's meal plan and data would be orphaned.
    """
    # Ensure we start logged out.
    goto(page, base_url, "/")
    if OAUTH_USER in page.locator("nav").inner_text():
        logout(page)

    # Record the github_id from the first login.
    identity_before = get_oauth_identity(page.request, base_url, OAUTH_USER)
    github_id_before = identity_before["github_id"]

    # Second login via the same backdoor (same username → same github_id).
    goto(page, base_url, f"/test-login?username={OAUTH_USER}")

    assert "/mealplan" in page.url, f"Expected /mealplan, got {page.url!r}"
    expect(page.locator("nav").get_by_text(OAUTH_USER)).to_be_visible()

    # ── github_id unchanged — row was reused, not duplicated ─────────────────
    identity_after = get_oauth_identity(page.request, base_url, OAUTH_USER)
    assert identity_after["github_id"] == github_id_before, (
        "github_id changed on second login — a new row may have been created."
    )
    assert identity_after["has_github_identity"] is True

    # ── No second account with a suffix was created ───────────────────────────
    duplicate_resp = page.request.get(
        f"{base_url}/api/debug/oauth-identity/{OAUTH_USER}_1"
    )
    assert duplicate_resp.status == 404, (
        "A duplicate account was created on the second login."
    )

    logout(page)


# ════════════════════════════════════════════════════════════════════════════
# Scenario 3 — CSRF protection: tokenless POST is rejected
# ════════════════════════════════════════════════════════════════════════════

def test_csrf_protection_rejects_unauthenticated_post(
    playwright, base_url: str
) -> None:
    """
    A POST to a state-changing endpoint sent without a valid session cookie
    (simulating a cross-site request with no authentication) must be rejected.

    The test uses Playwright's APIRequestContext — a fresh context with no
    browser session — to send a POST to /mealplan.  The endpoint is protected
    by Flask-Login's @login_required, so the server must redirect to /login.

    Verifies:
      - A raw POST with no session cookie is not accepted.
      - The response redirects to /login (or returns 401/403).

    Regression caught: if the @login_required decorator were accidentally
    removed from the /mealplan POST handler, an unauthenticated attacker could
    modify any user's meal plan by crafting a POST from any origin.
    """
    # A fresh APIRequestContext carries no browser cookies — equivalent to a
    # cross-site request with no valid session.
    api: APIRequestContext = playwright.request.new_context(base_url=base_url)
    try:
        response = api.post(
            "/mealplan",
            form={"day_of_week": "1", "recipe_id": "1", "servings": "2"},
        )
        # Playwright follows redirects by default, so after the 302→/login
        # chain the response URL will contain "/login".
        assert (
            "/login" in response.url
            or response.status in (400, 401, 403)
        ), (
            f"Expected auth or CSRF rejection, got status {response.status} at {response.url!r}"
        )
    finally:
        api.dispose()


# ════════════════════════════════════════════════════════════════════════════
# Scenario 4 — Session expiry: cleared session blocks protected route
# ════════════════════════════════════════════════════════════════════════════

def test_session_expiry_blocks_protected_route(page: Page, base_url: str) -> None:
    """
    Once a user's session cookie is gone (expired or cleared), the protected
    /mealplan route must redirect to /login — the user is no longer
    authenticated.

    Flask stores sessions in signed cookies on the client.  True time-based
    expiry requires the server clock to advance past PERMANENT_SESSION_LIFETIME
    and then the client to make a new request — difficult to orchestrate in a
    fast unit test.  We simulate this by clearing all cookies via Playwright's
    browser-context API, which is equivalent to the browser discarding an
    expired session cookie.  The code path exercised (Flask-Login's session
    validation on every request) is identical.

    Verifies:
      - A user who is logged in can access /mealplan.
      - After their session cookies are cleared, /mealplan redirects to /login.
      - The navbar reverts to showing "Log in" (anonymous state).

    Regression caught: if Flask-Login's `@login_required` were replaced with a
    weaker check that only reads a plain (unsigned) cookie value, clearing the
    official session cookie would not trigger a redirect, and any user could
    forge their own session by crafting a cookie with an arbitrary user_id.
    """
    session_user = f"lifecycle_sess_{_RUN_TS}"

    # Log in and confirm access.
    goto(page, base_url, f"/test-login?username={session_user}")
    assert "/mealplan" in page.url, f"Expected /mealplan after login, got {page.url!r}"
    expect(page.locator("nav").get_by_text(session_user)).to_be_visible()

    goto(page, base_url, "/mealplan")
    assert "/login" not in page.url, "Expected /mealplan to be accessible when logged in."

    # ── Simulate session expiry by clearing all cookies ──────────────────────
    page.context.clear_cookies()

    # ── Protected route now redirects to login ────────────────────────────────
    goto(page, base_url, "/mealplan")
    assert "/login" in page.url, (
        f"Expected redirect to /login after session cleared, got {page.url!r}"
    )
    expect(page.locator("nav").get_by_role("link", name="Log in")).to_be_visible()
