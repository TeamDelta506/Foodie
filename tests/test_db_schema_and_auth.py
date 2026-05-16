"""
tests/test_db_schema_and_auth.py

OWNED BY: Justin (db-and-security)
PURPOSE: Enforce database shape (tables, columns, FKs, uniqueness) and Flask-Login semantics per CONTRACTS.md §§1 and 4.

Committed by the coordinator Week 6; all tests RED until models + migrations + auth refactor ship.
"""

from __future__ import annotations

import os

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-secret"

import pytest  # noqa: E402
from sqlalchemy import inspect  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

from app import app, engine  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_schema():
    app.config["TESTING"] = True
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)


def test_recipes_table_exists_with_contract_columns():
    """recipes holds Edamam cache + default_servings per CONTRACTS.md §1."""
    inspector = inspect(engine)
    assert "recipes" in inspector.get_table_names()
    cols = {c["name"] for c in inspector.get_columns("recipes")}
    required = {
        "id",
        "api_id",
        "name",
        "image_url",
        "calories",
        "protein",
        "carbs",
        "fat",
        "default_servings",
        "created_at",
    }
    assert required.issubset(cols), f"missing recipe columns: {required - cols}"


def test_ingredients_table_foreign_keys():
    """ingredients.recipe_id → recipes.id with ON DELETE CASCADE."""
    inspector = inspect(engine)
    assert "ingredients" in inspector.get_table_names()
    fks = inspector.get_foreign_keys("ingredients")
    targets = {(fk["constrained_columns"][0], fk["referred_table"]) for fk in fks}
    assert ("recipe_id", "recipes") in targets


def test_mealplans_unique_user_day():
    """At most one meal per (user, weekday) — UNIQUE(user_id, day_of_week)."""
    inspector = inspect(engine)
    assert "mealplans" in inspector.get_table_names()
    uniques = inspector.get_unique_constraints("mealplans")
    if not uniques:
        indexes = inspector.get_indexes("mealplans")
        uq = [idx for idx in indexes if idx.get("unique")]
        names = [set(idx["column_names"]) for idx in uq]
        assert {"user_id", "day_of_week"} in names
    else:
        cols_sets = [set(u["column_names"]) for u in uniques]
        assert {"user_id", "day_of_week"} in cols_sets


def test_flask_login_initialized():
    """Flask-Login must be configured (LoginManager present)."""
    assert "login_manager" in app.extensions


@pytest.fixture
def client():
    with app.test_client() as c:
        yield c


def test_mealplan_get_requires_authenticated_user(client):
    """Anonymous GET /mealplan must redirect to login."""
    response = client.get("/mealplan", follow_redirects=False)
    assert response.status_code in (302, 401)


def _register(client, username: str, password: str = "secret") -> None:
    client.post("/register", data={"username": username, "password": password})
    client.post("/logout")


def _login(client, username: str, password: str = "secret") -> None:
    client.post("/login", data={"username": username, "password": password})


def test_mealplan_scoped_to_current_user(client):
    """User B must not see user A's meal-plan rows (CONTRACTS.md §4)."""
    from sqlmodel import Session, select

    from app import MealPlan, Recipe, User

    _register(client, "owner_a")
    _register(client, "owner_b")

    with Session(engine) as db:
        recipe = Recipe(api_id="iso-test", name="Isolation Recipe", default_servings=2)
        db.add(recipe)
        db.commit()
        db.refresh(recipe)
        recipe_id = recipe.id

    _login(client, "owner_a")
    client.post(
        "/mealplan",
        data={"day_of_week": "0", "recipe_id": str(recipe_id), "servings": "2"},
    )

    _login(client, "owner_b")
    response = client.get("/mealplan")
    assert response.status_code == 200
    assert b"Isolation Recipe" not in response.data

    with Session(engine) as db:
        user_b = db.exec(select(User).where(User.username == "owner_b")).first()
        rows = db.exec(select(MealPlan).where(MealPlan.user_id == user_b.id)).all()
        assert rows == []


def test_mealplan_delete_missing_day_returns_404(client):
    """DELETE /mealplan/<day> with no plan for current user returns 404, not 403."""
    _register(client, "deleter")
    _login(client, "deleter")
    response = client.delete("/mealplan/3", follow_redirects=False)
    assert response.status_code == 404
