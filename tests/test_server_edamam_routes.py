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

from app import app, engine, _edamam_image_url  # noqa: E402

_EDAMAM_RE = re.compile(r"https://api\.edamam\.com/api/recipes/v2\?.*")
_EDAMAM_RECIPE_BY_ID = re.compile(r"https://api\.edamam\.com/api/recipes/v2/[^?]+")


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
                        "images": {"REGULAR": {"url": "https://cdn.example/test-tomato.jpg"}},
                        "image": "https://cdn.example/test-tomato-legacy.jpg",
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


def test_edamam_image_url_prefers_regular_then_legacy_image_field():
    """Parser checks all common Edamam image shapes (cached recipes need a URL)."""
    assert _edamam_image_url({
        "images": {"REGULAR": {"url": "https://cdn.example/regular.jpg"}},
        "image": "https://cdn.example/legacy.jpg",
    }) == "https://cdn.example/regular.jpg"
    assert _edamam_image_url({
        "images": {"SMALL": {"url": "https://cdn.example/small.jpg"}},
    }) == "https://cdn.example/small.jpg"
    assert _edamam_image_url({"image": "https://cdn.example/top.jpg"}) == "https://cdn.example/top.jpg"
    assert _edamam_image_url({}) is None


def test_image_content_type_accepts_s3_octet_stream_jpeg():
    """Edamam S3 serves JPEG bytes as binary/octet-stream — proxy must still accept them."""
    from app import _image_content_type  # noqa: E402

    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 12
    assert _image_content_type("binary/octet-stream", "https://example.com/x.jpg", jpeg) == "image/jpeg"
    assert _image_content_type("application/octet-stream", "https://example.com/x", jpeg) == "image/jpeg"


@responses.activate
def test_recipe_image_accepts_octet_stream_from_upstream(client, monkeypatch):
    """GET /recipes/<id>/image succeeds when upstream uses binary/octet-stream."""
    monkeypatch.setenv("DISABLE_EDAMAM_API", "0")
    from sqlmodel import Session, select

    from app import Recipe  # noqa: E402

    api_id = "http://www.edamam.com/ontologies/edamam.owl#recipe_octet_test"
    with Session(engine) as db:
        db.add(Recipe(
            api_id=api_id,
            name="Octet soup",
            image_url="https://www.example.com/octet.jpg",
            default_servings=2,
        ))
        db.commit()
        recipe = db.exec(select(Recipe).where(Recipe.api_id == api_id)).first()
        assert recipe is not None
        rid = recipe.id

    responses.add(
        responses.GET,
        "https://www.example.com/octet.jpg",
        body=b"\xff\xd8\xff\xe0" + b"\x00" * 20,
        headers={"Content-Type": "binary/octet-stream"},
    )

    response = client.get(f"/recipes/{rid}/image")
    assert response.status_code == 200
    assert response.data[:3] == b"\xff\xd8\xff"
    assert response.headers["Content-Type"].startswith("image/jpeg")


def test_get_nutrition_json_shape(client):
    """GET /nutrition/<id> returns JSON with macro keys for a cached recipe id."""
    response = client.get("/nutrition/1?servings=2")
    assert response.status_code == 200
    assert response.is_json
    data = response.get_json()
    for key in ("recipe_id", "servings", "calories", "protein", "carbs", "fat"):
        assert key in data


@responses.activate
def test_recipe_image_refreshes_expired_presigned_url(client, monkeypatch):
    """403 from expired S3 URL triggers one Edamam lookup and retries with fresh URL."""
    monkeypatch.setenv("DISABLE_EDAMAM_API", "0")
    from sqlmodel import Session, select

    from app import Recipe  # noqa: E402

    api_id = "http://www.edamam.com/ontologies/edamam.owl#recipe_refresh_test"
    with Session(engine) as db:
        db.add(Recipe(
            api_id=api_id,
            name="Stale Soup",
            image_url="https://www.example.com/expired.jpg",
            default_servings=2,
        ))
        db.commit()
        recipe = db.exec(select(Recipe).where(Recipe.api_id == api_id)).first()
        assert recipe is not None
        rid = recipe.id

    responses.add(responses.GET, "https://www.example.com/expired.jpg", status=403)
    responses.add(
        responses.GET,
        _EDAMAM_RECIPE_BY_ID,
        json={
            "recipe": {
                "uri": api_id,
                "label": "Stale Soup",
                "images": {"REGULAR": {"url": "https://www.example.com/fresh.jpg"}},
            }
        },
        status=200,
    )
    responses.add(
        responses.GET,
        "https://www.example.com/fresh.jpg",
        body=b"\xff\xd8fakejpeg",
        headers={"Content-Type": "image/jpeg"},
    )

    response = client.get(f"/recipes/{rid}/image")
    assert response.status_code == 200
    assert response.data == b"\xff\xd8fakejpeg"

    with Session(engine) as db:
        updated = db.get(Recipe, rid)
        assert updated is not None
        assert updated.image_url == "https://www.example.com/fresh.jpg"


@responses.activate
def test_recipe_image_backfills_missing_url_from_edamam(client, monkeypatch):
    """Recipe rows with image_url=NULL can fetch a URL on first /recipes/<id>/image hit."""
    monkeypatch.setenv("DISABLE_EDAMAM_API", "0")
    from sqlmodel import Session, select

    from app import Recipe  # noqa: E402

    api_id = "http://www.edamam.com/ontologies/edamam.owl#recipe_missing_img"
    with Session(engine) as db:
        db.add(Recipe(
            api_id=api_id,
            name="No Image Yet",
            image_url=None,
            default_servings=2,
        ))
        db.commit()
        recipe = db.exec(select(Recipe).where(Recipe.api_id == api_id)).first()
        assert recipe is not None
        rid = recipe.id

    responses.add(
        responses.GET,
        _EDAMAM_RECIPE_BY_ID,
        json={
            "recipe": {
                "uri": api_id,
                "label": "No Image Yet",
                "images": {"REGULAR": {"url": "https://www.example.com/new.jpg"}},
            }
        },
        status=200,
    )
    responses.add(
        responses.GET,
        "https://www.example.com/new.jpg",
        body=b"\xff\xd8newimg",
        headers={"Content-Type": "image/jpeg"},
    )

    response = client.get(f"/recipes/{rid}/image")
    assert response.status_code == 200
    assert response.data == b"\xff\xd8newimg"
