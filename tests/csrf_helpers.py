"""CSRF token helpers for Flask test client POSTs (Week 7 — db-and-security)."""

from __future__ import annotations

import re
import weakref

_META_RE = re.compile(rb'meta\s+name="csrf-token"\s+content="([^"]+)"')
_HIDDEN_RE = re.compile(rb'name="csrf_token"[^>]*value="([^"]+)"')

_csrf_cache: dict[int, str] = {}
_csrf_client_refs: dict[int, weakref.ref] = {}


def _invalidate_cache(ref: weakref.ref) -> None:
    """Remove cached token when the test client is garbage-collected."""
    for key, r in list(_csrf_client_refs.items()):
        if r is ref:
            _csrf_cache.pop(key, None)
            _csrf_client_refs.pop(key, None)
            break


def fetch_csrf_token(client) -> str:
    """Return a CSRF token, cached for the lifetime of this test client.

    Flask-WTF reuses the same token within a session, so one GET is enough
    per test-client instance.  The cache is keyed by ``id(client)`` and
    cleaned up via weak-ref callback when the client is collected.
    """
    key = id(client)
    token = _csrf_cache.get(key)
    if token is not None:
        return token

    response = client.get("/")
    assert response.status_code == 200
    match = _META_RE.search(response.data) or _HIDDEN_RE.search(response.data)
    assert match, "csrf-token meta tag or hidden field not found in response"
    token = match.group(1).decode()

    _csrf_cache[key] = token
    try:
        _csrf_client_refs[key] = weakref.ref(client, _invalidate_cache)
    except TypeError:
        pass
    return token


def post_with_csrf(client, url: str, data: dict | None = None, **kwargs):
    """POST with csrf_token merged into form data."""
    payload = dict(data or {})
    payload["csrf_token"] = fetch_csrf_token(client)
    return client.post(url, data=payload, **kwargs)


def post_json_with_csrf(client, url: str, json_data: dict, **kwargs):
    """JSON POST with X-CSRFToken header."""
    headers = dict(kwargs.pop("headers", {}) or {})
    headers["X-CSRFToken"] = fetch_csrf_token(client)
    headers.setdefault("Content-Type", "application/json")
    return client.post(url, json=json_data, headers=headers, **kwargs)


def delete_with_csrf(client, url: str, **kwargs):
    """DELETE with X-CSRFToken header."""
    headers = dict(kwargs.pop("headers", {}) or {})
    headers["X-CSRFToken"] = fetch_csrf_token(client)
    return client.delete(url, headers=headers, **kwargs)
