"""
tests/e2e/test_client_side_login.py
=====================================
Playwright end-to-end tests for the client-side OAuth UX slice.

Covers:
  - "Sign in with GitHub" button visible on the login page (alongside the
    password form, which must NOT be removed).
  - Clicking the button, completing login via the /test-login backdoor
    (simulating a successful GitHub callback), and seeing the username in
    the navbar.
  - "Remember me" checkbox present and ticked state persists through submit.
  - Post-login landing page is deliberate: home page with username visible.
  - Logout clears the session and returns to home with "Log in" link.

Walk adapted from e2e/server_side.md (Week 6), steps 3–4.
OAuth step inserted at the top using the /test-login backdoor.

Run (from repo root, with app running and ENABLE_TEST_LOGIN=1):
    ENABLE_TEST_LOGIN=1 pytest tests/e2e/test_client_side_login.py -v
    ENABLE_TEST_LOGIN=1 pytest tests/e2e/test_client_side_login.py -v --headed
"""

from __future__ import annotations

import re
import time

import pytest
from playwright.sync_api import Page, Route, expect


TEST_USERNAME = f"pw_client_{int(time.time())}"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def goto(page: Page, base_url: str, path: str) -> None:
    page.goto(f"{base_url}{path}")


# ---------------------------------------------------------------------------
# Test 1 — Full client-side GitHub OAuth UX happy path
# ---------------------------------------------------------------------------

def test_client_side_github_login(page: Page, base_url: str) -> None:
    """
    A logged-out user clicks "Sign in with GitHub", the OAuth redirect is
    intercepted and replaced by the test-login backdoor, and the user lands
    on the home page with their username visible in the navbar.

    Walk:
      0. Login page shows both the password form AND the GitHub button.
      1. Click "Continue with GitHub" → browser navigates to /login/github.
      2. /login/github redirects to github.com/login/oauth/authorize.
      3. page.route() intercepts that external URL and sends the browser to
         /test-login instead (simulating a completed GitHub callback).
      4. Home page loads — username appears in the navbar.
      5. The alert on home page shows "Logged in as <username>".
      6. /mealplan is accessible (session is live).
      7. Logout clears the session — navbar reverts to "Log in".
    """

    # Intercept /login/github on *our* server before the browser is sent to
    # GitHub.  The server returns a 302 to github.com; we short-circuit that
    # by fulfilling the /login/github request ourselves with a redirect straight
    # to /test-login, which simulates a completed OAuth callback.
    def _intercept_github(route: Route) -> None:
        if "/login/github" in route.request.url:
            route.fulfill(
                status=302,
                headers={"Location": f"{base_url}/test-login?username={TEST_USERNAME}"},
                body="",
            )
        else:
            route.continue_()

    page.route(f"{base_url}/login/github", _intercept_github)

    # ── 0. Login page: both forms present ───────────────────────────────────
    goto(page, base_url, "/login")

    # Password form must still exist (Week 8 will revisit it).
    expect(page.locator('input[name="username"]')).to_be_visible()
    expect(page.locator('input[name="password"]')).to_be_visible()

    # "Remember me" checkbox must be present.
    expect(page.locator('input[name="remember"]')).to_be_visible()

    # GitHub button must be present.
    github_btn = page.get_by_role("link", name=re.compile(r"github", re.IGNORECASE))
    expect(github_btn).to_be_visible()

    # ── 1–3. Click GitHub button → intercepted → test-login → mealplan ───────
    github_btn.click()

    page.wait_for_url("**/mealplan**", timeout=10_000)
    assert "/mealplan" in page.url, (
        f"Expected /mealplan after OAuth, got {page.url!r}"
    )

    # ── 4. Username visible in the navbar ────────────────────────────────────
    nav_user = page.locator("nav").get_by_text(TEST_USERNAME)
    expect(nav_user).to_be_visible()

    # ── 5. Flash / home-page alert shows "Logged in as <username>" ───────────
    body_text = page.locator("body").inner_text()
    assert TEST_USERNAME in body_text, (
        f"Expected '{TEST_USERNAME}' on page after login, not found."
    )

    # ── 6. Protected route /mealplan accessible with live session ────────────
    goto(page, base_url, "/mealplan")
    assert "/login" not in page.url, (
        f"Expected /mealplan accessible, got redirect to {page.url!r}"
    )
    expect(page.locator("[data-day]")).to_have_count(7)

    # ── 7. Logout clears session ─────────────────────────────────────────────
    page.locator("form[action*='logout'] button").click()
    expect(page.locator("nav").get_by_role("link", name="Log in")).to_be_visible()
    expect(page.locator("body")).not_to_contain_text(TEST_USERNAME)


# ---------------------------------------------------------------------------
# Test 2 — Login page structure (both auth paths always present)
# ---------------------------------------------------------------------------

def test_login_page_has_both_auth_paths(page: Page, base_url: str) -> None:
    """
    The login page must keep the username+password form alongside the GitHub
    button — neither should be removed while the other exists.
    """
    goto(page, base_url, "/login")

    # Password-based form fields.
    expect(page.locator('input[name="username"]')).to_be_visible()
    expect(page.locator('input[name="password"]')).to_be_visible()
    expect(page.locator('input[name="remember"]')).to_be_visible()
    expect(page.get_by_role("button", name="Log in with password")).to_be_visible()

    # OAuth path.
    expect(
        page.get_by_role("link", name=re.compile(r"github", re.IGNORECASE))
    ).to_be_visible()


# ---------------------------------------------------------------------------
# Test 3 — Remember me checkbox ticked flows through to submit
# ---------------------------------------------------------------------------

def test_remember_checkbox(page: Page, base_url: str) -> None:
    """
    The "Remember me" checkbox (`name="remember"`, value `y`) works on password login.
    After login the user lands on /mealplan (CONTRACTS.md §3).
    Uses the registered-user path via /test-login to seed the account, then
    logs in with the password form.
    """
    # Seed a test account via the backdoor.
    remember_user = f"pw_remember_{int(time.time())}"
    goto(page, base_url, f"/test-login?username={remember_user}")
    # Log back out so we can test the form login with Remember me.
    page.locator("form[action*='logout'] button").click()
    expect(page.locator("nav").get_by_role("link", name="Log in")).to_be_visible()

    # The test account was created without a password; register a fresh one
    # that has a real password so form login works.
    pw_user  = f"pw_rem2_{int(time.time())}"
    pw_pass  = "testpassword123"
    goto(page, base_url, "/register")
    page.fill('input[name="username"]', pw_user)
    page.fill('input[name="password"]', pw_pass)
    page.get_by_role("button", name="Create account").click()
    # Now logged in from register — log out.
    page.locator("form[action*='logout'] button").click()

    # Log in via the form with Remember me ticked.
    goto(page, base_url, "/login")
    page.fill('input[name="username"]', pw_user)
    page.fill('input[name="password"]', pw_pass)
    page.check('input[name="remember"]')
    page.get_by_role("button", name="Log in with password").click()

    page.wait_for_url("**/mealplan**", timeout=8_000)
    expect(page.locator("nav").get_by_text(pw_user)).to_be_visible()

    # Flask-Login remember_token cookie — proves Remember me reached the server.
    cookies = page.context.cookies()
    assert any(c["name"] == "remember_token" for c in cookies), (
        "Expected remember_token cookie after login with Remember me checked."
    )


# ---------------------------------------------------------------------------
# Test 4 — Post-login landing page is the home page (deliberate, not random)
# ---------------------------------------------------------------------------

def test_post_login_lands_on_mealplan(page: Page, base_url: str) -> None:
    """
    After completing OAuth (via test-login backdoor), the user lands on
    /mealplan — the Week 7 deliberate post-login page (CONTRACTS.md §3).
    """
    user = f"pw_land_{int(time.time())}"
    goto(page, base_url, f"/test-login?username={user}")
    assert "/mealplan" in page.url, (
        f"Expected deliberate redirect to /mealplan, got {page.url!r}"
    )
    expect(page.locator("nav").get_by_text(user)).to_be_visible()
