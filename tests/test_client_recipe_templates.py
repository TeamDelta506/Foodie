"""
tests/test_client_recipe_templates.py

OWNED BY: Asia (client-side)
PURPOSE: Structural checks (forms, actions, nav hooks) for templates per CONTRACTS.md §3 using BeautifulSoup — NOT literal marketing copy.

Committed Week 6 by coordinator; these fail until Asia's templates + Sam routes exist.
"""

from __future__ import annotations

import os

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-secret"

import pytest  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

from app import app, engine  # noqa: E402


@pytest.fixture
def client():
    app.config["TESTING"] = True
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    with app.test_client() as c:
        yield c


def test_recipes_search_template_has_get_form_with_q(client):
    """Search page exposes GET /recipes/search with `q` text input."""
    response = client.get("/recipes/search")
    assert response.status_code == 200
    soup = BeautifulSoup(response.data, "html.parser")
    forms = soup.find_all("form")
    match = None
    for form in forms:
        action = (form.get("action") or "").strip()
        method = (form.get("method") or "get").lower()
        if method == "get" and "/recipes/search" in action.replace(" ", ""):
            match = form
            break
    assert match is not None, "Expected GET search form posting to /recipes/search"
    assert match.find("input", attrs={"name": "q"}) is not None


def test_base_nav_includes_recipes_discover_link(client):
    """Navbar exposes a discover/search entry (href contains /recipes/search)."""
    response = client.get("/")
    assert response.status_code == 200
    html = response.data.decode()
    assert "/recipes/search" in html


def test_mealplan_page_has_seven_day_slots(client):
    """Meal plan UI materializes 7 weekday rows/cards — structural hook data-day attributes."""
    client.post("/register", data={"username": "htmltest", "password": "password123"})
    response = client.get("/mealplan")
    assert response.status_code == 200
    soup = BeautifulSoup(response.data, "html.parser")
    day_nodes = soup.select("[data-day]")
    assert len(day_nodes) == 7


def test_mealplan_page_has_post_form_for_add(client):
    """Logged-in meal plan view includes POST /mealplan form w/ day + recipe + servings fields."""
    client.post("/register", data={"username": "plantest", "password": "password123"})
    response = client.get("/mealplan")
    assert response.status_code == 200
    soup = BeautifulSoup(response.data, "html.parser")
    form = soup.find("form", attrs={"action": "/mealplan"})
    assert form is not None
    for name in ("day_of_week", "recipe_id", "servings"):
        assert form.find(attrs={"name": name}) is not None
