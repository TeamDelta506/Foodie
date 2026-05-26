"""Pytest discovery anchor — also ensures the repo root is on sys.path so
`from app import app, db` works from the tests/ directory."""

import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Defaults for pytest when .env is absent (CI / local unit tests).
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("OAUTH_CLIENT_ID", "test-oauth-client-id")
os.environ.setdefault("OAUTH_CLIENT_SECRET", "test-oauth-client-secret")
os.environ.setdefault("ENABLE_TEST_LOGIN", "1")
os.environ.setdefault("DISABLE_EDAMAM_API", "1")

_CSRF_FIELD_RE = re.compile(r'name="csrf_token"[^>]*value="([^"]+)"', re.I)
_CSRF_META_RE = re.compile(r'<meta[^>]+name="csrf-token"[^>]+content="([^"]+)"', re.I)


def _csrf_from_html(html: str) -> str:
    match = _CSRF_FIELD_RE.search(html) or _CSRF_META_RE.search(html)
    assert match, "csrf_token not found in HTML"
    return match.group(1)


def fetch_csrf_token(client, url: str = "/login") -> str:
    """Read a CSRF token using the test client's session cookie."""
    response = client.get(url)
    return _csrf_from_html(response.data.decode())


def csrf_post(client, url: str, data: dict | None = None, *, token_url: str = "/login", **kwargs):
    """POST with a valid csrf_token field (CONTRACTS.md §10)."""
    payload = dict(data or {})
    payload["csrf_token"] = fetch_csrf_token(client, token_url)
    return client.post(url, data=payload, **kwargs)


def csrf_delete(client, url: str, *, token_url: str = "/mealplan", **kwargs):
    """DELETE with X-CSRFToken header bound to the client's session."""
    headers = dict(kwargs.pop("headers", {}) or {})
    headers["X-CSRFToken"] = fetch_csrf_token(client, token_url)
    return client.delete(url, headers=headers, **kwargs)
