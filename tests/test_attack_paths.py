"""
tests/test_attack_paths.py
===========================
Script-kiddie attack-path test (Study Guide §10).

Asserts that nginx *refuses* every known-bad URL in attack_paths.json at the
edge — the request returns 404/403 AND never reaches the Flask process. The
body-size check distinguishes an nginx `return 404` (tiny default page) from a
Flask 404 (large branded error.html), so a path that is merely proxied and
404'd by the app will FAIL this test.

Requirements:
  - docker compose -f docker-compose.prod.yml up -d must be running.
  - The self-signed cert is accepted via verify=False (urllib3 warning suppressed).

Run:
  pytest tests/test_attack_paths.py -v

Expected: 20 PASSED, one per attack path.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PATHS_FILE = _REPO_ROOT / "attack_paths.json"

with _PATHS_FILE.open() as f:
    PATHS: list[str] = json.load(f)

BASE = os.environ.get("ATTACK_TEST_BASE", "https://localhost")


# nginx's built-in error page is tiny (~150 bytes). Flask's branded error.html
# is several KB. A bare status check can't tell the two apart: a 404 *from Flask*
# passes just as well as a 404 *from nginx*, even though the request still woke a
# gunicorn worker. We bound the body size so the test fails if the path was
# proxied to the app instead of being refused at the edge.
_EDGE_MAX_BODY_BYTES = 1024


@pytest.mark.parametrize("path", PATHS)
def test_nginx_blocks(path: str) -> None:
    """nginx must refuse every known-bad path at the edge (404/403, not via Flask)."""
    r = requests.get(BASE + path, verify=False, timeout=5, allow_redirects=False)
    assert r.status_code in (404, 403), (
        f"{path!r} returned HTTP {r.status_code} — nginx let it through to Flask"
    )
    # A large body means Flask's error page answered — the request reached the
    # app instead of being blocked by an nginx `return 404`.
    assert len(r.content) < _EDGE_MAX_BODY_BYTES, (
        f"{path!r} returned a {len(r.content)}-byte body — looks like Flask served "
        f"it, not nginx. The path is being proxied, not blocked at the edge."
    )


def test_flask_never_saw_any_of_them() -> None:
    """If a gunicorn access log exists, assert no attack path appears in it."""
    log_path = _REPO_ROOT / "logs" / "flask.log"
    if not log_path.exists():
        pytest.skip(
            "logs/flask.log not present — "
            "set accesslog = 'logs/flask.log' in gunicorn.conf.py to enable this check"
        )

    log_contents = log_path.read_text()
    leaks = [p for p in PATHS if p in log_contents]
    assert not leaks, (
        f"Flask saw {len(leaks)} attack path(s) that nginx should have blocked: "
        + ", ".join(leaks)
    )
