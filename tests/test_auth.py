"""
Course 506 Week 5 Skeleton — basic tests for the auth flow + S3 site routes.

These run in CI on every PR (see .github/workflows/test.yml) and locally with
`pytest` from the repo root. The pattern mirrors Week 4's regression test:
fast, automated, gates the merge.

Tests use SQLite in-memory so we don't need Postgres in CI. The Flask app
reads DATABASE_URL from env, so this override applies before the app loads.
"""

import os

# These must be set BEFORE importing app.py — environment-driven config.
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-secret"

import pytest
from sqlmodel import SQLModel, select
from app import app, engine, User, Session
from tests.conftest import csrf_post

from tests.csrf_helpers import fetch_csrf_token, post_with_csrf


@pytest.fixture
def client():
    app.config["TESTING"] = True

    # Reset schema for each test — drop and recreate.
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)

    with app.test_client() as client:
        yield client


def test_home_page_loads(client):
    """Flask-rendered home page returns 200 and has the navbar."""
    response = client.get("/")
    assert response.status_code == 200
    assert b"Foodie" in response.data
    assert b"Discover recipes" in response.data or b"/recipes/search" in response.data
    assert b"About" in response.data


def test_site_home_redirects_when_no_synced_index(client):
    """When S3_content/ has no index.html, /site/ redirects away from the empty static tree."""
    response = client.get("/site/", follow_redirects=False)
    if response.status_code == 302:
        assert "/site" not in (response.location or "").lower()
    else:
        assert response.status_code == 200


def test_login_page_renders(client):
    """The login form is reachable."""
    response = client.get("/login")
    assert response.status_code == 200
    assert b"login" in response.data.lower()


def test_register_creates_user_in_database(client):
    """Registering a user writes a row to the users table."""
    post_with_csrf(
        client,
        "/register",
        {"username": "alice", "password": "password123"},
    )
    csrf_post(client, "/register", {"username": "alice", "password": "password123"})

    with Session(engine) as db:
        user = db.exec(select(User).where(User.username == "alice")).first()
        assert user is not None
        assert user.password_hash != "password123"  # password was hashed


def test_register_rejects_duplicate_username(client):
    """A second register with the same username flashes 'already taken'."""
    post_with_csrf(client, "/register", {"username": "bob", "password": "password123"})
    post_with_csrf(client, "/logout")
    response = post_with_csrf(
    csrf_post(client, "/register", {"username": "bob", "password": "password123"})
    csrf_post(client, "/logout")
    response = csrf_post(
        client,
        "/register",
        {"username": "bob", "password": "different"},
        follow_redirects=True,
    )
    assert b"already taken" in response.data


def test_login_with_wrong_password_shows_invalid(client):
    """Wrong password shows the 'Invalid' flash on the login page."""
    post_with_csrf(client, "/register", {"username": "dave", "password": "secret"})
    post_with_csrf(client, "/logout")

    response = post_with_csrf(
    csrf_post(client, "/register", {"username": "dave", "password": "secret"})
    csrf_post(client, "/logout")

    response = csrf_post(
        client,
        "/login",
        {"username": "dave", "password": "wrong"},
        follow_redirects=True,
    )
    assert b"Invalid" in response.data


def test_login_redirects_mealplan_with_session(client):
    """Week 7 — successful password login redirects to /mealplan (CONTRACTS.md §3)."""
    post_with_csrf(client, "/register", {"username": "carol", "password": "secret"})
    post_with_csrf(client, "/logout")

    response = post_with_csrf(
    csrf_post(client, "/register", {"username": "carol", "password": "secret"})
    csrf_post(client, "/logout")

    response = csrf_post(
        client,
        "/login",
        {"username": "carol", "password": "secret"},
    )
    assert response.status_code == 302
    assert response.location.endswith("/mealplan")

    # Flask-Login stores the authenticated user id under '_user_id'
    with client.session_transaction() as sess:
        assert "_user_id" in sess


def test_login_with_remember_sets_remember_cookie(client):
    """Remember me sets Flask-Login remember_token (CONTRACTS.md §9–§10)."""
    csrf_post(client, "/register", {"username": "rem_user", "password": "secret123"})
    csrf_post(client, "/logout")

    response = csrf_post(
        client,
        "/login",
        {"username": "rem_user", "password": "secret123", "remember": "y"},
    )
    assert response.status_code == 302
    set_cookies = response.headers.getlist("Set-Cookie")
    assert any("remember_token" in c for c in set_cookies)


def test_login_without_remember_omits_remember_cookie(client):
    """Unchecked Remember me must not issue remember_token."""
    csrf_post(client, "/register", {"username": "norem_user", "password": "secret123"})
    csrf_post(client, "/logout")

    response = csrf_post(
        client,
        "/login",
        {"username": "norem_user", "password": "secret123"},
    )
    assert response.status_code == 302
    set_cookies = response.headers.getlist("Set-Cookie")
    assert not any("remember_token" in c for c in set_cookies)


def test_oauth_only_user_cannot_password_login(client):
    """password_hash=NULL accounts get generic invalid-password flash (CONTRACTS.md §1)."""
    from app import User, Session

    with Session(engine) as db:
        db.add(User(username="github_only", password_hash=None))
        db.commit()

    response = csrf_post(
        client,
        "/login",
        {"username": "github_only", "password": "any-password"},
        follow_redirects=True,
    )
    assert b"Invalid" in response.data
