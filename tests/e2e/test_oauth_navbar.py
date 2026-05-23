"""Asia Playwright — GitHub entry + test-login backdoor → navbar username (CONTRACTS.md §12)."""
from __future__ import annotations

from playwright.sync_api import Page, expect

E2E_USERNAME = "e2e_github_user"


def test_github_sign_in_shows_username_in_navbar(page: Page, base_url):
    """Logged-out user clicks Sign in with GitHub; backdoor completes login; username in navbar."""
    base = base_url

    def _oauth_start_redirects_to_backdoor(route):
        route.fulfill(
            status=302,
            headers={"Location": f"{base}/test/login/{E2E_USERNAME}"},
        )

    page.route("**/login/github**", _oauth_start_redirects_to_backdoor)

    page.goto(f"{base}/login")
    expect(page.locator(".foodie-nav-user")).to_have_count(0)

    github = page.get_by_role("link", name="Sign in with GitHub")
    expect(github).to_be_visible()

    with page.expect_navigation(url="**/mealplan**"):
        github.click()

    navbar_user = page.locator(".foodie-nav-user")
    expect(navbar_user).to_be_visible()
    expect(navbar_user).to_contain_text("Logged in as")
    expect(navbar_user.locator(".fw-semibold")).to_have_text(E2E_USERNAME)
