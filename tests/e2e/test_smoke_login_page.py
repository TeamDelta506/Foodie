"""Coordinator Playwright smoke — login page + GitHub button (CONTRACTS.md §12)."""
from playwright.sync_api import Page, expect


def test_app_starts_login_page_has_clickable_github_button(page: Page, base_url):
    page.goto(f"{base_url}/login")
    expect(page).to_have_title("Log in — Foodie")
    github = page.get_by_role("link", name="Sign in with GitHub")
    expect(github).to_be_visible()
    expect(github).to_be_enabled()
    expect(github).to_have_attribute("href", "/login/github")
    # Do not click — that starts a real GitHub OAuth redirect and wastes API quota in CI/dev.
