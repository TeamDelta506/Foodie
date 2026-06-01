"""
tests/e2e/test_oauth_login_happy_path.py
========================================
Sam — Playwright happy-path OAuth login (CONTRACTS.md §3, §12).

Uses /test-login backdoor (§11) to simulate a completed GitHub callback.
Asserts deliberate landing on /mealplan and **Logged in as {username}** in the UI.

Run:
    ENABLE_TEST_LOGIN=1 pytest tests/e2e/test_oauth_login_happy_path.py -v
"""

from __future__ import annotations

import re
import time

import pytest
from playwright.sync_api import Page, expect

TEST_USERNAME = f"pw_oauth_{int(time.time())}"


def goto(page: Page, base_url: str, path: str) -> None:
    page.goto(f"{base_url}{path}")


def test_oauth_login_happy_path(page: Page, base_url: str) -> None:
    """
    Logged-out user → /test-login (OAuth stand-in) → /mealplan with username visible.

    CONTRACTS.md §3: success lands on /mealplan; §9 navbar shows Logged in as {username}.
    """
    goto(page, base_url, "/")
    expect(page.locator("nav").get_by_role("link", name="Log in")).to_be_visible()
    expect(page.locator("body")).not_to_contain_text(TEST_USERNAME)

    goto(page, base_url, "/login")
    github_btn = page.get_by_role("link", name=re.compile(r"sign in with github", re.IGNORECASE))
    expect(github_btn).to_be_visible()
    assert "/login/github" in (github_btn.get_attribute("href") or "")

    goto(page, base_url, f"/test-login?username={TEST_USERNAME}")

    assert "/mealplan" in page.url, f"Expected /mealplan, got {page.url!r}"
    expect(page.locator("body")).to_contain_text("Logged in as")
    expect(page.locator(".foodie-nav-user")).to_contain_text(TEST_USERNAME)

    identity = page.request.get(f"{base_url}/api/debug/oauth-identity/{TEST_USERNAME}")
    assert identity.ok
    data = identity.json()
    assert data["has_github_identity"] is True
    assert data["provider_user_id"] == f"test_{TEST_USERNAME}"

    goto(page, base_url, "/mealplan")
    assert "/login" not in page.url
    expect(page.locator("[data-day]")).to_have_count(7)

    page.locator("form[action*='logout'] button").click()
    expect(page.locator("nav").get_by_role("link", name="Log in")).to_be_visible()
    expect(page.locator("body")).not_to_contain_text(TEST_USERNAME)


def test_test_login_idempotent(page: Page, base_url: str) -> None:
    """Second /test-login with same username reuses oauth_identities row (no duplicate)."""
    fixed_user = f"pw_idempotent_{int(time.time())}"

    goto(page, base_url, f"/test-login?username={fixed_user}")
    first_id = page.request.get(f"{base_url}/api/debug/oauth-identity/{fixed_user}").json()["provider_user_id"]

    page.locator("form[action*='logout'] button").click()

    goto(page, base_url, f"/test-login?username={fixed_user}")
    second_id = page.request.get(f"{base_url}/api/debug/oauth-identity/{fixed_user}").json()["provider_user_id"]
    assert first_id == second_id == f"test_{fixed_user}"


def test_test_login_disabled_without_env(page: Page, base_url: str) -> None:
    import os

    if os.environ.get("ENABLE_TEST_LOGIN", "").lower() in ("1", "true"):
        pytest.skip("ENABLE_TEST_LOGIN is set — /test-login is intentionally open.")

    response = page.goto(f"{base_url}/test-login?username=should_not_exist")
    assert response is not None and response.status == 404
