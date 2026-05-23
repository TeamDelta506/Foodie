"""Playwright e2e fixtures — Week 7 (CONTRACTS.md §11).

Self-contained: spins up a Werkzeug dev server on a random free port so
tests run without a separately-started Flask process.  Works on Windows,
macOS, and Linux.
"""
from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path

import pytest

# ── Hermetic SQLite DB (temp dir is cross-platform) ──────────────────────────
_E2E_DB = Path(tempfile.gettempdir()) / "foodie_e2e_test.db"
if _E2E_DB.exists():
    try:
        _E2E_DB.unlink()
    except OSError:
        pass

# Set env vars BEFORE importing app so SQLAlchemy + Authlib pick up the right values.
os.environ["DATABASE_URL"]          = f"sqlite:///{_E2E_DB}"
os.environ["SECRET_KEY"]            = "e2e-test-secret-key"
os.environ["GITHUB_CLIENT_ID"]      = "e2e-test-github-client-id"
os.environ["GITHUB_CLIENT_SECRET"]  = "e2e-test-github-client-secret"
os.environ["ENABLE_TEST_LOGIN"]     = "1"          # unlocks /test-login backdoor

from sqlmodel import SQLModel          # noqa: E402
from app import app, engine            # noqa: E402


# ── One-time schema creation ──────────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def _e2e_schema():
    app.config["TESTING"] = True
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    yield
    SQLModel.metadata.drop_all(engine)
    try:
        _E2E_DB.unlink(missing_ok=True)
    except OSError:
        pass  # Windows: file may still be held by the live-server thread


# ── Embedded Werkzeug server (random free port) ───────────────────────────────

@pytest.fixture(scope="session")
def live_server():
    """Start a threaded Werkzeug server on a random free port."""
    from werkzeug.serving import make_server

    server = make_server("127.0.0.1", 0, app)
    port   = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    class _Info:
        url = f"http://127.0.0.1:{port}"

    yield _Info()
    server.shutdown()


# ── Override pytest-playwright's base_url to point at the live server ─────────

@pytest.fixture(scope="session")
def base_url(live_server) -> str:          # type: ignore[override]
    return live_server.url
