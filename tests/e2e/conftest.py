"""Playwright e2e fixtures — coordinator (CONTRACTS.md §11)."""
from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path

import pytest

# Hermetic SQLite + secrets before app import (Study Guide pattern).
_E2E_DB = Path(tempfile.gettempdir()) / "foodie_e2e_test.db"
if _E2E_DB.exists():
    _E2E_DB.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{_E2E_DB}"
os.environ["SECRET_KEY"] = "e2e-test-secret-key"
os.environ["OAUTH_CLIENT_ID"] = "e2e-test-oauth-client-id"
os.environ["OAUTH_CLIENT_SECRET"] = "e2e-test-oauth-client-secret"
os.environ["ENABLE_TEST_LOGIN"] = "1"
os.environ["DISABLE_EDAMAM_API"] = "1"

from sqlmodel import SQLModel  # noqa: E402

from app import app, engine  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _e2e_app_config():
    app.config["TESTING"] = True
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    yield
    SQLModel.metadata.drop_all(engine)
    if _E2E_DB.exists():
        try:
            _E2E_DB.unlink()
        except OSError:
            pass  # Windows: file may still be held by the live-server thread


@pytest.fixture(scope="session")
def live_server():
    """Threaded Werkzeug server for Playwright."""
    from werkzeug.serving import make_server

    app.config["TESTING"] = True
    server = make_server("127.0.0.1", 0, app)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    class _Server:
        url = f"http://127.0.0.1:{port}"

    yield _Server()
    server.shutdown()


@pytest.fixture(scope="session")
def base_url(live_server):
    """Sam's e2e tests expect `base_url`; coordinator fixture is `live_server`."""
    return live_server.url
