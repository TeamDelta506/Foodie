"""
tests/test_integration.py

OWNED BY: Sowmya Korasikha (coordinator)
PURPOSE: Register → search (mocked Edamam) → recipe detail → scale JSON → plan meal → planner view → clear day.
Passes only when Sam, Asia, and Justin ship work matching CONTRACTS.md.

Committed RED at Week 6 start; coordinator drives this file green last.
"""

from __future__ import annotations

import json
import os
import re

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-secret"
os.environ.setdefault("EDAMAM_APP_ID", "test-app-id")
os.environ.setdefault("EDAMAM_APP_KEY", "test-app-key")

import pytest  # noqa: E402
import responses  # noqa: E402

from app import app, engine  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402
from tests.csrf_helpers import delete_with_csrf, post_json_with_csrf, post_with_csrf  # noqa: E402
from tests.conftest import csrf_delete, csrf_post  # noqa: E402

_EDAMAM_RE = re.compile(r"https://api\.edamam\.com/api/recipes/v2\?.*")


@pytest.fixture
def client():
    app.config["TESTING"] = True
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    with app.test_client() as c:
        yield c


@responses.activate
def test_week6_demo_register_search_detail_scale_plan_delete(client):
    """Full-stack smoke aligned with CONTRACTS.md §8 (mocked Edamam)."""
    responses.add(
        responses.GET,
        _EDAMAM_RE,
        json={
            "hits": [
                {
                    "recipe": {
                        "uri": "edamam.integration.stub",
                        "label": "Integration Lentil Stew",
                        "images": {"REGULAR": {"url": "https://cdn.example/integration-lentil.jpg"}},
                        "yield": 2.0,
                        "calories": 640.0,
                        "totalNutrients": {},
                    }
                }
            ]
        },
        status=200,
    )

    assert post_with_csrf(
    assert csrf_post(
        client,
        "/register",
        {"username": "coord_user", "password": "password123"},
        follow_redirects=False,
    ).status_code == 302

    search = client.get("/recipes/search?q=lentil")
    assert search.status_code == 200
    assert b"Integration Lentil" in search.data

    html = search.data.decode()
    link = re.search(r'href="(/recipes/\d+)"', html)
    assert link is not None, "Search results should link to /recipes/<id> once implemented"
    detail_path = link.group(1)
    rid = int(detail_path.split("/")[-1])

    detail = client.get(detail_path)
    assert detail.status_code == 200

    nutrition = client.get(f"/nutrition/{rid}?servings=3")
    assert nutrition.status_code == 200
    nut = nutrition.get_json()
    assert nut["recipe_id"] == rid
    assert nut["servings"] == 3

    scale = post_json_with_csrf(
        client,
        "/recipes/scale",
        {"recipe_id": rid, "target_servings": 6},
    )
    assert scale.status_code == 200
    body = scale.get_json()
    assert body["target_servings"] == 6
    assert isinstance(body.get("ingredients"), list)

    plan = post_with_csrf(
        client,
        "/mealplan",
        {"day_of_week": "1", "recipe_id": str(rid), "servings": "2"},
    plan = csrf_post(
        client,
        "/mealplan",
        {"day_of_week": "1", "recipe_id": str(rid), "servings": "2"},
        token_url="/mealplan",
        follow_redirects=False,
    )
    assert plan.status_code == 302
    assert "/mealplan" in (plan.headers.get("Location") or "")

    board = client.get("/mealplan")
    assert board.status_code == 200
    assert str(rid).encode() in board.data

    clear = delete_with_csrf(client, "/mealplan/1")
    clear = csrf_delete(client, "/mealplan/1")
    assert clear.status_code == 302

    board_after = client.get("/mealplan")
    assert board_after.status_code == 200
    assert f'href="/recipes/{rid}"'.encode() not in board_after.data
    assert b"Integration Lentil" not in board_after.data
