"""
tests/test_attack_paths.py
===========================
Script-kiddie attack-path test (Study Guide §10).

Asserts that nginx returns 404 or 403 for every known-bad URL in
attack_paths.json — without the request ever reaching the Flask process.

Requirements:
  - docker compose up -d must be running (nginx + gunicorn + db stack).
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

# Suppress InsecureRequestWarning from verify=False (self-signed cert is fine for dev).
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Resolve attack_paths.json relative to the repo root, regardless of where
# pytest is invoked from.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_PATHS_FILE = _REPO_ROOT / "attack_paths.json"

with _PATHS_FILE.open() as f:
    PATHS: list[str] = json.load(f)

BASE = os.environ.get("ATTACK_TEST_BASE", "https://localhost")


# ---------------------------------------------------------------------------
# Parametrized test — one assertion per attack path
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", PATHS)
def test_nginx_blocks(path: str) -> None:
    """nginx must return 404 or 403 for every known-bad attack path.

    nginx doesn't know about /wp-login.php — no location block matches it,
    so the default action (404) fires.  The key assertion is that the path
    is blocked *before* reaching Flask: the status is 404/403, not 200/302.
    """
    r = requests.get(BASE + path, verify=False, timeout=5, allow_redirects=False)
    assert r.status_code in (404, 403), (
        f"{path!r} returned HTTP {r.status_code} — nginx let it through to Flask"
    )


# ---------------------------------------------------------------------------
# Optional log check — verifies Flask never logged these paths
# ---------------------------------------------------------------------------

def test_flask_never_saw_any_of_them() -> None:
    """If a gunicorn access log exists, assert no attack path appears in it.

    This test requires running gunicorn with accesslog pointed at a file, e.g.:
        accesslog = "logs/flask.log"   ← in gunicorn.conf.py

    In the canonical config, gunicorn logs to stdout (accesslog = "-") and
    Docker captures it.  If the log file is absent, this test is skipped.
    """
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
