"""Coordinator Playwright smoke — login page + GitHub button (CONTRACTS.md §12)."""
from playwright.sync_api import Page, expect


def test_app_starts_login_page_has_clickable_github_button(page: Page, live_server):
    page.goto(f"{live_server.url}/login")
    expect(page).to_have_title("Log in — Foodie")
    github = page.get_by_role("link", name="Sign in with GitHub")
    expect(github).to_be_visible()
    expect(github).to_be_enabled()
    expect(github).to_have_attribute("href", "/login/github")
    github.click()
