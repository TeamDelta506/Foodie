"""
tests/e2e/test_protected_page_auth.py
Justin (db-and-security) — Playwright end-to-end auth gate on /mealplan.

Verifies through the rendered DOM that the weekly meal planner is:
  - inaccessible when logged out (login page shown),
  - accessible after password register/login,
  - inaccessible again after logout.

Adapted from e2e/db_security.md step 8 (Week 6 DB-and-security browser walk).
Justin — protected-route auth gate (CONTRACTS.md §9, §12).

Verifies /mealplan is closed before login, open after the test-login backdoor,
and closed again after logout.
"""

from __future__ import annotations

import time

from playwright.sync_api import Page, expect


def _unique_username() -> str:
    return f"pw_protect_{time.time_ns()}"


def test_mealplan_protected_before_login_after_logout(page: Page, base_url: str) -> None:
    """Protected /mealplan: login form → planner → logout → login form again."""
    username = _unique_username()
    password = "secure-e2e-123"

    # ── 1. Anonymous: /mealplan redirects to login ─────────────────────────
    page.goto(f"{base_url}/mealplan")
    assert "/login" in page.url

    expect(page.locator("h1.foodie-page-heading")).to_have_text("Log in")
    expect(page.locator("h1", has_text="Weekly meal plan")).to_have_count(0)
    expect(page.locator("[data-day]")).to_have_count(0)
    expect(page.locator("nav").get_by_role("link", name="Log in")).to_be_visible()
    expect(page.locator("nav").get_by_text("Logged in as")).to_have_count(0)

    # ── 2. Register + land on meal plan ────────────────────────────────────
    page.goto(f"{base_url}/register")
    page.locator("#username").fill(username)
    page.locator("#password").fill(password)
    page.locator("#register-form button[type='submit']").click()

    page.wait_for_url(f"**{base_url}/mealplan**")
    expect(page.locator("h1.foodie-page-heading")).to_have_text("Weekly meal plan")
    expect(page.locator("[data-day]")).to_have_count(7)
    expect(page.locator("nav").get_by_role("link", name="Meal plan")).to_be_visible()
    expect(page.locator("nav").get_by_text(username)).to_be_visible()

    # ── 3. Logout ───────────────────────────────────────────────────────────
    page.locator("form[action*='logout'] button").click()
    expect(page.locator("nav").get_by_role("link", name="Log in")).to_be_visible()
    expect(page.locator("nav").get_by_text(username)).to_have_count(0)

    # ── 4. Anonymous again: planner content absent ───────────────────────────
    page.goto(f"{base_url}/mealplan")
    assert "/login" in page.url
    expect(page.locator("h1.foodie-page-heading")).to_have_text("Log in")
    expect(page.locator("[data-day]")).to_have_count(0)
TEST_USER = f"pw_protect_{int(time.time())}"


def goto(page: Page, base_url: str, path: str) -> None:
    page.goto(f"{base_url}{path}")


def test_mealplan_auth_gate(page: Page, base_url: str) -> None:
    """Anonymous users are redirected; logged-in users see the planner grid."""
    goto(page, base_url, "/mealplan")
    assert "/login" in page.url

    goto(page, base_url, f"/test-login?username={TEST_USER}")
    assert "/mealplan" in page.url
    expect(page.locator("[data-day]")).to_have_count(7)
    expect(page.locator(".foodie-nav-user")).to_contain_text(TEST_USER)

    page.locator("form[action*='logout'] button").click()
    expect(page.locator("nav").get_by_role("link", name="Log in")).to_be_visible()

    goto(page, base_url, "/mealplan")
    assert "/login" in page.url
