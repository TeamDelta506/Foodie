"""
tests/e2e/test_oauth_github_login.py
=====================================
Playwright end-to-end test for the GitHub OAuth happy-path login flow.

Adapted from the Week 6 server-side walkthrough (e2e/server_side.md steps 1–4).
The OAuth step replaces the manual register/login pair at the top: instead of
filling in a form, the test hits /test-login (the CI backdoor) which simulates
a completed GitHub callback and logs the user in immediately.

The rest of the walkthrough then verifies that the session is live and the
app's protected routes work as expected.

Requirements
------------
    pip install pytest-playwright
    playwright install chromium

Run (from repo root, with the app running locally and ENABLE_TEST_LOGIN=1):
    ENABLE_TEST_LOGIN=1 pytest tests/e2e/test_oauth_github_login.py -v
    ENABLE_TEST_LOGIN=1 pytest tests/e2e/test_oauth_github_login.py -v --headed
"""

from __future__ import annotations

import re
import time

import pytest
from playwright.sync_api import Page, expect


# Unique username for this test run so re-runs don't conflict on a live DB.
TEST_USERNAME = f"pw_oauth_{int(time.time())}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def goto(page: Page, base_url: str, path: str) -> None:
    page.goto(f"{base_url}{path}")


# ---------------------------------------------------------------------------
# Test 1 — GitHub OAuth happy-path login via /test-login backdoor
# ---------------------------------------------------------------------------

def test_github_oauth_happy_path_login(page: Page, base_url: str) -> None:
    """
    Full happy-path OAuth login flow.

    Walk (adapted from e2e/server_side.md, Week 6):
      0. Pre-condition: not logged in — navbar shows "Log in".
      1. Login page shows a "Continue with GitHub" button.
      2. Hit /test-login (simulates successful GitHub callback).
      3. Redirected to home page.
      4. Navbar shows "Logged in as <username>".
      5. /mealplan is accessible (session is live).
      6. Logout clears the session — navbar reverts to "Log in".
    """

    # ── 0. Verify anonymous state ────────────────────────────────────────────
    goto(page, base_url, "/")
    # Target the navbar "Log in" link specifically to avoid strict-mode
    # ambiguity (the home page has multiple "Log in" links).
    expect(page.locator("nav").get_by_role("link", name="Log in")).to_be_visible()
    # The username should NOT be visible yet.
    expect(page.locator("body")).not_to_contain_text(TEST_USERNAME)

    # ── 1. Login page has "Continue with GitHub" button ─────────────────────
    goto(page, base_url, "/login")
    github_btn = page.get_by_role("link", name=re.compile(r"github", re.IGNORECASE))
    expect(github_btn).to_be_visible()
    # Confirm it points at /login/github
    href = github_btn.get_attribute("href") or ""
    assert "/login/github" in href, f"Expected /login/github in href, got: {href!r}"

    # ── 2. Hit the test-login backdoor (simulates GitHub callback) ───────────
    goto(page, base_url, f"/test-login?username={TEST_USERNAME}")

    # ── 3. Redirected to home page ───────────────────────────────────────────
    assert page.url == f"{base_url}/", (
        f"Expected redirect to home page, got: {page.url!r}"
    )

    # ── 4. Navbar shows "Logged in as <username>" ────────────────────────────
    # The navbar must contain the username text somewhere visible.
    expect(page.locator("body")).to_contain_text(TEST_USERNAME)
    # Friendlier assertion: look for a flash or nav element with the username.
    # Accept either a flash message or just the username appearing in the nav.
    body_text = page.locator("body").inner_text()
    assert TEST_USERNAME in body_text, (
        f"Expected '{TEST_USERNAME}' visible after login, not found in page."
    )

    # ── 5. Protected route /mealplan is accessible with live session ─────────
    goto(page, base_url, "/mealplan")
    # Should NOT be redirected to /login (session is live).
    assert "/login" not in page.url, (
        f"Expected /mealplan accessible after login, was redirected to {page.url!r}"
    )
    expect(page.locator("[data-day]")).to_have_count(7)

    # ── 6. Logout clears session — navbar reverts to "Log in" ────────────────
    # Logout is a POST — click the logout button rather than navigating directly.
    logout_btn = page.locator("form[action*='logout'] button")
    if not logout_btn.is_visible():
        logout_btn = page.get_by_role("button", name=re.compile(r"log\s*out", re.IGNORECASE))
    logout_btn.click()

    # After logout: home page, navbar shows "Log in" again.
    expect(page.locator("nav").get_by_role("link", name="Log in")).to_be_visible()
    expect(page.locator("body")).not_to_contain_text(TEST_USERNAME)


# ---------------------------------------------------------------------------
# Test 2 — /test-login creates a new user on first call, reuses on repeat
# ---------------------------------------------------------------------------

def test_test_login_idempotent(page: Page, base_url: str) -> None:
    """
    Hitting /test-login twice with the same username should not create
    duplicate users or crash — it must log in the same account both times.
    """
    fixed_user = f"pw_idempotent_{int(time.time())}"

    # First login — creates the user.
    goto(page, base_url, f"/test-login?username={fixed_user}")
    expect(page.locator("body")).to_contain_text(fixed_user)

    # Logout.
    logout_btn = page.locator("form[action*='logout'] button")
    logout_btn.click()

    # Second login — must reuse the existing user, not crash.
    goto(page, base_url, f"/test-login?username={fixed_user}")
    expect(page.locator("body")).to_contain_text(fixed_user)


# ---------------------------------------------------------------------------
# Test 3 — /test-login is guarded (returns 404 without ENABLE_TEST_LOGIN=1)
# ---------------------------------------------------------------------------

def test_test_login_disabled_without_env(page: Page, base_url: str) -> None:
    """
    If ENABLE_TEST_LOGIN is not set the server should return 404.

    This test only runs when the flag is NOT set in the test process env,
    meaning the server was started without it.  When the flag IS set (normal
    e2e run), this test is skipped.
    """
    import os
    if os.environ.get("ENABLE_TEST_LOGIN", "").lower() in ("1", "true"):
        pytest.skip("ENABLE_TEST_LOGIN is set — /test-login is intentionally open.")

    response = page.goto(f"{base_url}/test-login?username=should_not_exist")
    assert response is not None and response.status == 404, (
        f"Expected 404 when ENABLE_TEST_LOGIN not set, got {response.status if response else 'None'}"
    )
