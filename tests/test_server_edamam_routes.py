"""
tests/test_server_edamam_routes.py

OWNED BY: Sam (server-side)
PURPOSE: Lock HTTP behavior + JSON envelopes for Edamam-backed routes per CONTRACTS.md §§3 and 5.

These tests were committed by the coordinator at the start of Week 6.
They intentionally FAIL until Sam wires `requests`, timeouts, and route tables.

Mocking: `responses` stubs `https://api.edamam.com/api/recipes/v2` — no real network.
"""

from __future__ import annotations

import json
import os
import re

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-secret"
# Tests should not depend on real keys; implementation reads real env in prod.
os.environ.setdefault("EDAMAM_APP_ID", "test-app-id")
os.environ.setdefault("EDAMAM_APP_KEY", "test-app-key")

import pytest  # noqa: E402
import requests  # noqa: E402
import responses  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

from app import app, engine  # noqa: E402

_EDAMAM_RE = re.compile(r"https://api\.edamam\.com/api/recipes/v2\?.*")


@pytest.fixture
def client():
    app.config["TESTING"] = True
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    with app.test_client() as c:
        yield c


@responses.activate
def test_recipes_search_returns_200_html_with_query_form(client):
    """GET /recipes/search serves the HTML shell + GET form with input name=q."""
    responses.add(
        responses.GET,
        _EDAMAM_RE,
        json={
            "hits": [
                {
                    "recipe": {
                        "uri": "edamam.recipe.internal_dummy_001",
                        "label": "Test Tomato Soup",
                        "image": None,
                        "yield": 2.0,
                        "calories": 400.0,
                        "totalNutrients": {},
                    }
                }
            ]
        },
        status=200,
    )

    response = client.get("/recipes/search?q=tomato")
    assert response.status_code == 200
    body = response.data.decode()
    assert 'name="q"' in body
    assert "/recipes/search" in body


@responses.activate
def test_recipes_search_upstream_timeout_sets_user_facing_flash(client):
    """On socket timeout, page still returns 200 and surfaces timeout messaging."""
    responses.add(
        responses.GET,
        _EDAMAM_RE,
        body=requests.exceptions.ReadTimeout(),
    )

    response = client.get("/recipes/search?q=anything")
    assert response.status_code == 200
    text = response.data.decode().lower()
    assert "timeout" in text


@responses.activate
def test_recipes_search_rate_limited_still_renders_200_banner(client):
    """429 from Edamam → 200 HTML + rate-limit messaging (per contract)."""
    responses.add(
        responses.GET,
        _EDAMAM_RE,
        status=429,
    )

    response = client.get("/recipes/search?q=rice")
    assert response.status_code == 200
    lowered = response.data.decode().lower()
    assert "rate" in lowered or "quota" in lowered or "429" in lowered


def test_post_scale_requires_authentication(client):
    """POST /recipes/scale must not succeed anonymously (302/401 gate)."""
    payload = {"recipe_id": 1, "target_servings": 4}
    response = client.post(
        "/recipes/scale",
        data=json.dumps(payload),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code in (302, 401)


def test_get_nutrition_json_shape(client):
    """GET /nutrition/<id> returns JSON with macro keys for a cached recipe id."""
    response = client.get("/nutrition/1?servings=2")
    assert response.status_code == 200
    assert response.is_json
    data = response.get_json()
    for key in ("recipe_id", "servings", "calories", "protein", "carbs", "fat"):
        assert key in data
