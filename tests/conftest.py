"""Pytest discovery anchor — also ensures the repo root is on sys.path so
`from app import app, db` works from the tests/ directory."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Defaults for pytest when .env is absent (CI / local unit tests).
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("OAUTH_CLIENT_ID", "test-oauth-client-id")
os.environ.setdefault("OAUTH_CLIENT_SECRET", "test-oauth-client-secret")
