"""
tests/e2e/test_protected_page_auth.py
=====================================
Justin — protected-route auth gate (CONTRACTS.md §9, §12).

Verifies /mealplan is closed before login, open after the test-login backdoor,
and closed again after logout.
"""

from __future__ import annotations

import time

from playwright.sync_api import Page, expect

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
