from __future__ import annotations

"""
Course 506 Week 7 — Flask + Postgres + SQLModel + GitHub OAuth + Playwright

Route ownership per CONTRACTS.md §7:
  Sam    — /recipes/search, /recipes/<id>, POST /recipes/scale,
            GET /nutrition/<id>, POST /mealplan, GET /mealplan,
            DELETE /mealplan/<day>; requests + Edamam wiring;
            /login/github, /auth/github/callback, /test-login (Week 7)
  Asia   — templates/, static/; login UX, Remember me (Week 7)
  Justin — SQLModel models; Flask-Login; DB schema (Week 7: github_id)
"""

import ipaddress
import logging
import os
import socket

from dotenv import load_dotenv

load_dotenv()  # before os.environ lookups (CONTRACTS.md §10)
import random
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import requests as http
from authlib.integrations.flask_client import OAuth
from flask import (
    Flask, render_template, request, redirect, url_for, flash, g,
    send_from_directory, abort, jsonify, session, Response,
)
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user, current_user,
    login_required,
)
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import (
    Column, DateTime, Integer, SmallInteger, ForeignKey,
    CheckConstraint, UniqueConstraint, event as sa_event, func, inspect, text,
)
from sqlmodel import SQLModel, Field, Session, create_engine, select
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash, check_password_hash

logger = logging.getLogger(__name__)


def _normalize_database_url(url: str) -> str:
    """Render/Heroku often provide postgres://; SQLAlchemy + psycopg2 need postgresql://."""
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://") :]
    return url


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)

# ---------------------------------------------------------------------------
# Application setup
# ---------------------------------------------------------------------------

app = Flask(__name__)
# Trust one proxy hop (nginx) so X-Forwarded-Proto enables secure session cookies over HTTPS.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-not-for-production")
# Session cookie hardening (CONTRACTS.md §10 — Justin / db-and-security).
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
# Remember-me cookie — 30 days, HttpOnly, SameSite=Lax (Week 7 client-side).
app.config["REMEMBER_COOKIE_DURATION"] = timedelta(days=30)
app.config["REMEMBER_COOKIE_HTTPONLY"] = True
app.config["REMEMBER_COOKIE_SAMESITE"] = "Lax"
# Permanent session lifetime — overridable via SESSION_LIFETIME_SECONDS for fast tests.
_sess_secs = int(os.environ.get("SESSION_LIFETIME_SECONDS", 0))
app.config["PERMANENT_SESSION_LIFETIME"] = (
    timedelta(seconds=_sess_secs) if _sess_secs else timedelta(days=7)
)
_on_render = os.environ.get("RENDER", "").lower() == "true"
_session_secure = os.environ.get("SESSION_COOKIE_SECURE")
if _session_secure is not None:
    app.config["SESSION_COOKIE_SECURE"] = _session_secure.lower() in ("1", "true", "yes")
elif _on_render:
    app.config["SESSION_COOKIE_SECURE"] = True

csrf = CSRFProtect(app)

DATABASE_URL = _normalize_database_url(
    os.environ.get("DATABASE_URL", "sqlite:///./foodie_dev.db")
)
OAUTH_CLIENT_ID     = os.environ.get("OAUTH_CLIENT_ID") or os.environ.get("GITHUB_CLIENT_ID", "")
OAUTH_CLIENT_SECRET = os.environ.get("OAUTH_CLIENT_SECRET") or os.environ.get("GITHUB_CLIENT_SECRET", "")

engine = create_engine(DATABASE_URL, echo=False)

# ---------------------------------------------------------------------------
# Authlib — GitHub OAuth (Week 7, server-side role)
# ---------------------------------------------------------------------------

oauth = OAuth(app)
github_oauth = oauth.register(
    name="github",
    client_id=OAUTH_CLIENT_ID,
    client_secret=OAUTH_CLIENT_SECRET,
    access_token_url="https://github.com/login/oauth/access_token",
    authorize_url="https://github.com/login/oauth/authorize",
    api_base_url="https://api.github.com/",
    client_kwargs={"scope": "read:user"},
)

S3_CONTENT_DIR = Path(__file__).parent / "S3_content"

EDAMAM_APP_ID  = os.environ.get("EDAMAM_APP_ID", "")
EDAMAM_APP_KEY = os.environ.get("EDAMAM_APP_KEY", "")
EDAMAM_BASE    = "https://api.edamam.com/api/recipes/v2"
EDAMAM_TIMEOUT = 4  # seconds per CONTRACTS.md §5

FEATURED_RECIPE_COUNT = 10
POPULAR_SEARCH_TERMS = (
    "chicken", "pasta", "salad", "soup", "salmon",
    "rice", "beef", "vegetarian", "breakfast", "tacos",
)


def _edamam_configured() -> bool:
    """True when server-side Edamam credentials are set (shared by all users)."""
    return bool(os.environ.get("EDAMAM_APP_ID") and os.environ.get("EDAMAM_APP_KEY"))


def _edamam_account_user() -> str:
    """Stable per-browser/user id — required by Edamam Recipe Search API v2."""
    if current_user.is_authenticated:
        return f"foodie-user-{current_user.id}"
    if "_edamam_uid" not in session:
        session["_edamam_uid"] = uuid.uuid4().hex[:12]
    return f"foodie-guest-{session['_edamam_uid']}"


def _edamam_request_headers() -> dict[str, str]:
    return {"Edamam-Account-User": _edamam_account_user()}


_DEMO_IMG_BOWL   = "/static/img/demo/bowl.jpg"
_DEMO_IMG_SALMON = "/static/img/demo/salmon.jpg"

# ---------------------------------------------------------------------------
# Flask-Login
# ---------------------------------------------------------------------------

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.init_app(app)
# Flask-Login 0.6.x sets app.login_manager directly; also register in
# app.extensions so test_flask_login_initialized passes.
app.extensions["login_manager"] = login_manager


# ---------------------------------------------------------------------------
# Database models (Justin — CONTRACTS.md §1)
# ---------------------------------------------------------------------------

class User(UserMixin, SQLModel, table=True):
    __tablename__ = "users"

    id:            int | None  = Field(default=None, primary_key=True)
    username:      str         = Field(unique=True, index=True, max_length=80)
    # Nullable — OAuth-only accounts have no local password.
    password_hash: str | None  = Field(default=None, max_length=255, nullable=True)
    created_at:    datetime = Field(
        default_factory=_utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=func.now()),
    )
    # Legacy mirror of oauth_identities (Week 7); prefer oauth_identities for lookups.
    github_id:    str | None = Field(default=None, max_length=64,  unique=True, index=True)
    github_login: str | None = Field(default=None, max_length=255)


class OAuthIdentity(SQLModel, table=True):
    """Links external OAuth accounts to local users (CONTRACTS.md §1)."""

    __tablename__ = "oauth_identities"
    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_oauth_provider_user"),
    )

    id:               int | None  = Field(default=None, primary_key=True)
    user_id:          int         = Field(
        sa_column=Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    )
    provider:         str         = Field(max_length=32)
    provider_user_id: str         = Field(max_length=64)
    provider_login:   str | None  = Field(default=None, max_length=80)
    created_at:       datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=func.now()),
    )


class Recipe(SQLModel, table=True):
    __tablename__ = "recipes"
    __table_args__ = (
        CheckConstraint("default_servings > 0", name="ck_recipes_default_servings"),
    )

    id:               int | None  = Field(default=None, primary_key=True)
    api_id:           str         = Field(unique=True, index=True, max_length=255)
    name:             str         = Field(max_length=500)
    image_url:        str | None  = Field(default=None, max_length=2048)
    calories:         float | None = Field(default=None)
    protein:          float | None = Field(default=None)
    carbs:            float | None = Field(default=None)
    fat:              float | None = Field(default=None)
    default_servings: int         = Field()
    created_at:       datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=func.now()),
    )


class Ingredient(SQLModel, table=True):
    __tablename__ = "ingredients"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_ingredients_quantity"),
    )

    id:        int | None = Field(default=None, primary_key=True)
    recipe_id: int        = Field(
        sa_column=Column(Integer, ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False)
    )
    name:      str        = Field(max_length=300)
    quantity:  float      = Field()
    unit:      str        = Field(max_length=50)


class MealPlan(SQLModel, table=True):
    __tablename__ = "mealplans"
    __table_args__ = (
        UniqueConstraint("user_id", "day_of_week", name="uq_mealplans_user_day"),
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_mealplans_day_of_week"),
        CheckConstraint("servings > 0", name="ck_mealplans_servings"),
    )

    id:          int | None = Field(default=None, primary_key=True)
    user_id:     int        = Field(
        sa_column=Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    )
    day_of_week: int        = Field(sa_column=Column(SmallInteger, nullable=False))
    recipe_id:   int        = Field(
        sa_column=Column(Integer, ForeignKey("recipes.id", ondelete="RESTRICT"), nullable=False)
    )
    servings:    int        = Field()


# ---------------------------------------------------------------------------
# Demo seed — two fully working sample recipes (images + ingredients) for
# offline backup when Edamam is unavailable. Placeholder rows were removed.
# ---------------------------------------------------------------------------

_NOW = lambda: datetime.now(timezone.utc)  # noqa: E731


def _sync_recipes_id_sequence(connection) -> None:
    """Explicit demo ids leave Postgres serial low; bump before Edamam inserts."""
    if connection.dialect.name != "postgresql":
        return
    connection.execute(
        text(
            "SELECT setval("
            "pg_get_serial_sequence('recipes', 'id'), "
            "(SELECT COALESCE(MAX(id), 1) FROM recipes)"
            ")"
        )
    )


@sa_event.listens_for(Recipe.__table__, "after_create")
def _seed_demo_recipes(target, connection, **kwargs):
    connection.execute(
        target.insert(),
        [
            {
                "id": 1, "api_id": "demo.grain_bowl", "name": "Garden grain bowl",
                "image_url": _DEMO_IMG_BOWL, "calories": 420.0, "protein": 18.0,
                "carbs": 55.0, "fat": 12.0, "default_servings": 2, "created_at": _NOW(),
            },
            {
                "id": 2, "api_id": "demo.citrus_salmon", "name": "Citrus herb salmon",
                "image_url": _DEMO_IMG_SALMON, "calories": 560.0, "protein": 48.0,
                "carbs": 8.0, "fat": 32.0, "default_servings": 4, "created_at": _NOW(),
            },
        ],
    )
    _sync_recipes_id_sequence(connection)


def _purge_legacy_placeholder_demos() -> None:
    """Drop old demo.p* rows from databases created before placeholder removal."""
    with Session(engine) as db:
        legacy = db.exec(
            select(Recipe).where(Recipe.api_id.like("demo.p%"))  # type: ignore[arg-type]
        ).all()
        if not legacy:
            return
        for recipe in legacy:
            for plan in db.exec(
                select(MealPlan).where(MealPlan.recipe_id == recipe.id)
            ).all():
                db.delete(plan)
            db.delete(recipe)
        db.commit()


@sa_event.listens_for(Ingredient.__table__, "after_create")
def _seed_demo_ingredients(target, connection, **kwargs):
    connection.execute(
        target.insert(),
        [
            {"recipe_id": 1, "name": "Quinoa",       "quantity": 1.0, "unit": "cup"},
            {"recipe_id": 1, "name": "Kale",          "quantity": 2.0, "unit": "cup"},
            {"recipe_id": 1, "name": "Lemon juice",   "quantity": 2.0, "unit": "tbsp"},
            {"recipe_id": 2, "name": "Salmon fillet", "quantity": 1.5, "unit": "lb"},
            {"recipe_id": 2, "name": "Fresh dill",    "quantity": 2.0, "unit": "tbsp"},
            {"recipe_id": 2, "name": "Orange zest",   "quantity": 1.0, "unit": "tsp"},
        ],
    )


# ---------------------------------------------------------------------------
# Edamam response parser (Sam — CONTRACTS.md §5)
# ---------------------------------------------------------------------------

_EDAMAM_IMAGE_SIZE_KEYS = (
    "REGULAR", "LARGE", "SMALL", "THUMBNAIL",
    "regular", "large", "small", "thumbnail",
)


def _edamam_image_url(recipe_data: dict) -> str | None:
    """Best recipe image URL from an Edamam hits[] recipe object."""
    images = recipe_data.get("images") or {}
    for key in _EDAMAM_IMAGE_SIZE_KEYS:
        entry = images.get(key)
        if isinstance(entry, dict):
            url = (entry.get("url") or "").strip()
            if url:
                return url
        elif isinstance(entry, str) and entry.strip().startswith(("http://", "https://")):
            return entry.strip()
    top = recipe_data.get("image")
    if isinstance(top, str) and top.strip().startswith(("http://", "https://")):
        return top.strip()
    return None


def _parse_and_upsert_hit(hit: dict, db: Session) -> "Recipe | None":
    """Parse one Edamam hits[] entry and upsert into recipes + ingredients.

    Nutrient keys: PROCNT=protein, CHOCDF=carbs, FAT=fat.
    ingredientLines stored as single-item rows (quantity=1, unit=portion)
    until a structured NLP parse pass is added.
    """
    recipe_data = hit.get("recipe", {})
    api_id = (recipe_data.get("uri") or "").strip()
    name   = (recipe_data.get("label") or "").strip()
    if not api_id or not name:
        return None

    image_url = _edamam_image_url(recipe_data)

    existing = db.exec(select(Recipe).where(Recipe.api_id == api_id)).first()
    if existing:
        # Refresh cached image URL when Edamam returns one (e.g. row saved before parser fix).
        if image_url and image_url != existing.image_url:
            existing.image_url = image_url
            db.add(existing)
            db.commit()
            db.refresh(existing)
        return existing

    def _macro(key: str) -> "float | None":
        n = (recipe_data.get("totalNutrients") or {}).get(key, {})
        qty = n.get("quantity")
        return float(qty) if qty is not None else None

    recipe = Recipe(
        api_id=api_id,
        name=name,
        image_url=image_url,
        calories=recipe_data.get("calories"),
        protein=_macro("PROCNT"),
        carbs=_macro("CHOCDF"),
        fat=_macro("FAT"),
        default_servings=max(1, int(recipe_data.get("yield") or 1)),
    )
    db.add(recipe)
    db.commit()
    db.refresh(recipe)

    for line in (recipe_data.get("ingredientLines") or []):
        db.add(Ingredient(recipe_id=recipe.id, name=line, quantity=1.0, unit="portion"))
    db.commit()

    return recipe


def _count_non_demo_recipes(db: Session) -> int:
    row = db.exec(
        select(func.count()).select_from(Recipe).where(Recipe.api_id.not_like("demo.p%"))  # type: ignore[arg-type]
    ).one()
    return int(row)


def _featured_recipes(db: Session, limit: int = FEATURED_RECIPE_COUNT) -> list[Recipe]:
    """Random sample of cached real recipes (excludes Week 5/6 demo rows)."""
    stmt = (
        select(Recipe)
        .where(Recipe.api_id.not_like("demo.p%"))  # type: ignore[arg-type]
        .order_by(func.random())
        .limit(limit)
    )
    return list(db.exec(stmt).all())


def _bootstrap_featured_recipes(db: Session) -> str | None:
    """One Edamam call per session to seed popular dishes when the cache is thin."""
    if _count_non_demo_recipes(db) >= FEATURED_RECIPE_COUNT:
        return None
    # Never burn Edamam quota during pytest / Playwright (template tests hit this route).
    if app.config.get("TESTING"):
        return None
    if os.environ.get("DISABLE_EDAMAM_API", "").lower() in ("1", "true", "yes"):
        return None
    if not _edamam_configured() or session.get("_featured_bootstrap_done"):
        return None
    if session.get("_edamam_rate_limited"):
        return "rate_limited"

    session["_featured_bootstrap_done"] = True
    term = random.choice(POPULAR_SEARCH_TERMS)
    _, err = _edamam_search_recipes(term, db)
    if err == "rate_limited":
        session["_edamam_rate_limited"] = True
    return err


def _edamam_search_recipes(q: str, db: Session) -> tuple[list[Recipe], str | None]:
    """Call Edamam for `q`, upsert hits, return recipes and optional error code."""
    try:
        resp = http.get(
            EDAMAM_BASE,
            params={
                "type": "public",
                "q": q,
                "app_id": EDAMAM_APP_ID,
                "app_key": EDAMAM_APP_KEY,
            },
            headers=_edamam_request_headers(),
            timeout=EDAMAM_TIMEOUT,
        )
    except http.exceptions.ReadTimeout:
        return [], "timeout"
    except http.exceptions.RequestException:
        logger.exception("Edamam request failed")
        return [], "upstream_error"

    if resp.status_code == 429 or (
        not resp.ok and "usage" in (resp.text or "").lower()
    ):
        return [], "rate_limited"
    if not resp.ok:
        if resp.status_code in (401, 403):
            logger.error("Edamam auth error %s — check API keys", resp.status_code)
        else:
            logger.error("Edamam upstream error: HTTP %s", resp.status_code)
        return [], "upstream_error"

    try:
        hits = resp.json().get("hits", [])
    except (ValueError, KeyError, AttributeError):
        logger.exception("Could not parse Edamam response")
        return [], "upstream_invalid"

    recipes: list[Recipe] = []
    for hit in hits:
        recipe = _parse_and_upsert_hit(hit, db)
        if recipe is not None:
            recipes.append(recipe)
    return recipes, None


def _is_demo_recipe(recipe: Recipe) -> bool:
    return recipe.api_id.startswith("demo.")


def _refresh_recipe_image_from_edamam(recipe: Recipe, db: Session) -> str | None:
    """Renew one recipe's presigned image URL via Edamam's per-recipe endpoint."""
    if os.environ.get("DISABLE_EDAMAM_API", "").lower() in ("1", "true", "yes"):
        return None
    if not _edamam_configured() or _is_demo_recipe(recipe) or not recipe.api_id:
        return None

    lookup_url = f"{EDAMAM_BASE}/{quote(recipe.api_id, safe='')}"
    try:
        resp = http.get(
            lookup_url,
            params={
                "type": "public",
                "app_id": EDAMAM_APP_ID,
                "app_key": EDAMAM_APP_KEY,
            },
            headers=_edamam_request_headers(),
            timeout=EDAMAM_TIMEOUT,
        )
    except http.RequestException:
        logger.exception("Edamam image refresh failed for recipe_id=%s", recipe.id)
        return None

    if resp.status_code == 429:
        session["_edamam_rate_limited"] = True
        return None
    if not resp.ok:
        logger.warning(
            "Edamam recipe lookup HTTP %s for recipe_id=%s",
            resp.status_code,
            recipe.id,
        )
        return None

    try:
        payload = resp.json()
    except ValueError:
        logger.exception("Edamam recipe lookup returned invalid JSON for recipe_id=%s", recipe.id)
        return None

    recipe_data = payload.get("recipe") if isinstance(payload, dict) else None
    if not isinstance(recipe_data, dict):
        return None

    new_url = _edamam_image_url(recipe_data)
    if not new_url:
        return None

    if new_url != recipe.image_url:
        recipe.image_url = new_url
        db.add(recipe)
        db.commit()
        db.refresh(recipe)
    return new_url


def _image_content_type(header_value: str | None, url: str, data: bytes) -> str | None:
    """Resolve Content-Type; Edamam S3 often serves JPEG as binary/octet-stream."""
    ct = (header_value or "").split(";")[0].strip().lower()
    if ct.startswith("image/"):
        return ct
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    path = urlparse(url).path.lower()
    if path.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if path.endswith(".png"):
        return "image/png"
    if path.endswith(".webp"):
        return "image/webp"
    if path.endswith(".gif"):
        return "image/gif"
    return None


def _s3_presigned_url_is_stale(url: str, *, skew_seconds: int = 60) -> bool:
    """True when URL looks like AWS SigV4 presigned and is past expiry."""
    try:
        qs = parse_qs(urlparse(url).query)
        date_raw = (qs.get("X-Amz-Date") or [None])[0]
        expires_raw = (qs.get("X-Amz-Expires") or [None])[0]
        if not date_raw or not expires_raw:
            return False
        issued = datetime.strptime(date_raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        expires_sec = int(expires_raw)
        return datetime.now(timezone.utc) >= issued + timedelta(seconds=expires_sec - skew_seconds)
    except (ValueError, TypeError, OverflowError):
        return False


def _fetch_remote_image(url: str) -> tuple[Response | None, int | None]:
    """Fetch a remote image URL. Returns (response, None) or (None, http_status)."""
    upstream = http.get(
        url,
        timeout=EDAMAM_TIMEOUT,
        headers={"User-Agent": "Foodie/1.0", "Accept": "image/*"},
    )
    if not upstream.ok:
        return None, upstream.status_code

    data = upstream.content
    content_type = _image_content_type(upstream.headers.get("Content-Type"), url, data)
    if not content_type or not data:
        return None, upstream.status_code

    return Response(
        data,
        content_type=content_type,
        headers={"Cache-Control": "public, max-age=86400"},
    ), None


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------

def get_db_session():
    if "db_session" not in g:
        g.db_session = Session(engine)
    return g.db_session


def _public_recipe_image_url(recipe_id: int | None, image_url: str | None) -> str | None:
    """Browser-safe image URL: local paths as-is, remote Edamam URLs via same-origin proxy."""
    if not image_url:
        return None
    url = image_url.strip()
    if url.startswith("/"):
        return url
    if recipe_id is not None:
        return url_for("recipe_image", recipe_id=recipe_id)
    return None


def _safe_remote_image_url(url: str) -> str | None:
    """SSRF guard — only fetch remote images from public hosts."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    try:
        for info in socket.getaddrinfo(parsed.hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return None
    except socket.gaierror:
        return None
    return url.strip()


@app.template_filter("recipe_image_src")
def recipe_image_src_filter(image_url: str | None, recipe_id: int | None = None) -> str:
    return _public_recipe_image_url(recipe_id, image_url) or ""


@app.teardown_appcontext
def close_db_session(exception=None):
    db_session = g.pop("db_session", None)
    if db_session is not None:
        db_session.close()


@login_manager.user_loader
def load_user(user_id):
    db = get_db_session()
    return db.get(User, int(user_id))


@app.context_processor
def inject_user():
    return {"user": current_user if current_user.is_authenticated else None}


# ---------------------------------------------------------------------------
# Error handler
# ---------------------------------------------------------------------------

@app.errorhandler(HTTPException)
def handle_http_exception(e: HTTPException):
    code = e.code or 500
    desc = (e.description or "").strip()

    if code == 404:
        page_title = "Page not found — Foodie"
        heading    = "We can't find that page"
        lead       = "The address may be mistyped, or the recipe or page may no longer be here."
    elif code == 403:
        page_title = "Access denied — Foodie"
        heading    = "You can't open this"
        lead       = desc or "You don't have permission to view this resource. Try signing in with a different account."
    elif code == 405:
        page_title = "Method not allowed — Foodie"
        heading    = "That action isn't supported here"
        lead       = desc or "Use the navigation or buttons on a Foodie page instead of this address."
    elif code >= 500:
        page_title = "Something went wrong — Foodie"
        heading    = "Server hiccup"
        lead       = "Please try again in a moment. If the problem continues, come back later."
    else:
        page_title = "Request problem — Foodie"
        heading    = "We couldn't complete that request"
        lead       = desc or "Try going back, or use the shortcuts below."

    return (
        render_template(
            "error.html",
            page_title=page_title,
            error_code=code,
            error_heading=heading,
            error_lead=lead,
        ),
        code,
    )


# ---------------------------------------------------------------------------
# Routes — static S3 site
# ---------------------------------------------------------------------------

@app.route("/")
def home():
    return render_template("home.html")


@app.route("/site/")
def site_home():
    index_path = S3_CONTENT_DIR / "index.html"
    if not index_path.exists():
        return redirect(url_for("home"))
    return send_from_directory(S3_CONTENT_DIR, "index.html")


@app.route("/site/<path:filename>")
def serve_s3_content(filename):
    file_path = S3_CONTENT_DIR / filename
    if not file_path.exists() or not file_path.is_file():
        abort(404)
    return send_from_directory(S3_CONTENT_DIR, filename)


# ---------------------------------------------------------------------------
# Routes — authentication
# ---------------------------------------------------------------------------

_GITHUB_PROVIDER = "github"
_OAUTH_FAIL_FLASH = "GitHub sign-in failed. Try again or use password login."


def _remember_checked() -> bool:
    """CONTRACTS.md §3 — checkbox name `remember`, value `y` when checked."""
    return request.form.get("remember") in ("y", "on", "true", "1")


def _github_identity_by_provider_id(db: Session, provider_user_id: str) -> OAuthIdentity | None:
    return db.exec(
        select(OAuthIdentity).where(
            OAuthIdentity.provider == _GITHUB_PROVIDER,
            OAuthIdentity.provider_user_id == provider_user_id,
        )
    ).first()


def _user_has_github_identity(db: Session, user_id: int) -> bool:
    return db.exec(
        select(OAuthIdentity).where(
            OAuthIdentity.user_id == user_id,
            OAuthIdentity.provider == _GITHUB_PROVIDER,
        )
    ).first() is not None


def _link_github_identity(
    db: Session, user: User, provider_user_id: str, provider_login: str | None
) -> None:
    """Insert oauth_identities row and sync legacy users.github_* columns."""
    if _github_identity_by_provider_id(db, provider_user_id):
        return
    db.add(
        OAuthIdentity(
            user_id=user.id,
            provider=_GITHUB_PROVIDER,
            provider_user_id=provider_user_id,
            provider_login=(provider_login or "")[:80] or None,
        )
    )
    user.github_id = provider_user_id
    user.github_login = provider_login
    db.add(user)
    db.commit()


def _free_username_for_github(db: Session, github_login: str | None, github_id: str) -> str:
    """New-account username when no linkable local row exists (CONTRACTS.md §3)."""
    base = (github_login or f"github-{github_id}")[:80]
    candidate = base
    suffix = 1
    while db.exec(select(User).where(User.username == candidate)).first():
        candidate = f"{base[:74]}-{github_id}"[:80] if suffix == 1 else f"{base[:70]}_{suffix}"[:80]
        suffix += 1
        if suffix > 99:
            return f"github-{github_id}"[:80]
    return candidate


def _ensure_test_github_identity(db: Session, user: User, handle: str) -> str:
    """Backdoor identity — CONTRACTS.md §11; provider_user_id test_<username>."""
    provider_user_id = f"test_{handle}"
    if not _github_identity_by_provider_id(db, provider_user_id):
        _link_github_identity(db, user, provider_user_id, handle)
    return provider_user_id


def _post_login_redirect():
    """Week 7 deliberate landing page after successful auth (CONTRACTS.md §3)."""
    next_url = request.form.get("next") or request.args.get("next") or ""
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return redirect(next_url)
    return redirect(url_for("mealplan"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    if not username or not password:
        flash("Username and password are required.")
        return redirect(url_for("register"))

    db = get_db_session()
    if db.exec(select(User).where(User.username == username)).first() is not None:
        flash("That username is already taken.")
        return redirect(url_for("register"))

    user = User(username=username, password_hash=generate_password_hash(password))
    db.add(user)
    db.commit()
    db.refresh(user)
    session.permanent = True
    login_user(user, remember=_remember_checked())
    return _post_login_redirect()


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    username  = request.form.get("username", "").strip()
    password  = request.form.get("password", "")

    db   = get_db_session()
    user = db.exec(select(User).where(User.username == username)).first()

    if user is None or user.password_hash is None or not check_password_hash(user.password_hash, password):
        flash("Invalid username or password.")
        return redirect(url_for("login"))

    session.permanent = True
    login_user(user, remember=_remember_checked())
    return _post_login_redirect()


@app.route("/logout", methods=["POST"])
def logout():
    logout_user()
    flash("You have been logged out.")
    return redirect(url_for("home"))


@app.route("/test/login/<username>")
def test_login_legacy(username: str):
    """Legacy path-based test backdoor kept for existing pytest tests."""
    if not app.config.get("TESTING"):
        abort(404)
    db = get_db_session()
    user = db.exec(select(User).where(User.username == username)).first()
    if user is None:
        user = User(username=username, password_hash=None)
        db.add(user)
        db.commit()
        db.refresh(user)
    _ensure_test_github_identity(db, user, username)
    session.permanent = True
    login_user(user)
    return redirect(url_for("mealplan"))


@app.route("/about")
def about():
    return render_template("about.html")


# ---------------------------------------------------------------------------
# Routes — GitHub OAuth (Week 7, server-side role)
# ---------------------------------------------------------------------------

@app.route("/login/github")
def login_github():
    """Redirect to GitHub's OAuth authorisation page."""
    if request.args.get("remember") == "y":
        session["remember_oauth"] = True
    next_url = request.args.get("next", "")
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        session["next"] = next_url
    redirect_uri = url_for("auth_github_callback", _external=True)
    return github_oauth.authorize_redirect(redirect_uri)


@app.route("/auth/github/callback")
def auth_github_callback():
    """OAuth callback — create-or-link via oauth_identities (CONTRACTS.md §3)."""
    try:
        token = github_oauth.authorize_access_token()
    except Exception:
        logger.warning("GitHub OAuth token exchange failed", exc_info=True)
        flash(_OAUTH_FAIL_FLASH)
        return redirect(url_for("login"))

    resp = github_oauth.get("user", token=token)
    profile: dict = resp.json() if resp.ok else {}

    raw_id = profile.get("id")
    if raw_id is None:
        logger.warning("GitHub profile missing id: %s", profile)
        flash(_OAUTH_FAIL_FLASH)
        return redirect(url_for("login"))

    provider_user_id = str(raw_id)
    provider_login = profile.get("login") or None

    remember = session.pop("remember_oauth", False)
    next_url = session.pop("next", None)
    db = get_db_session()

    def _oauth_done(user: User):
        session.permanent = True
        login_user(user, remember=remember)
        flash(f"Logged in as {user.username}")
        if next_url and next_url.startswith("/") and not next_url.startswith("//"):
            return redirect(next_url)
        return redirect(url_for("mealplan"))

    # Returning GitHub user — lookup oauth_identities first.
    identity = _github_identity_by_provider_id(db, provider_user_id)
    if identity:
        user = db.get(User, identity.user_id)
        if user is not None:
            return _oauth_done(user)

    # Logged-in local user linking GitHub.
    if current_user.is_authenticated:
        user = db.get(User, int(current_user.get_id()))
        if user is not None:
            _link_github_identity(db, user, provider_user_id, provider_login)
            return _oauth_done(user)

    # New user — link to existing username without identity, or create.
    preferred = (provider_login or f"github-{provider_user_id}")[:80]
    existing = db.exec(select(User).where(User.username == preferred)).first()
    if existing is not None and not _user_has_github_identity(db, existing.id):
        _link_github_identity(db, existing, provider_user_id, provider_login)
        return _oauth_done(existing)

    username = _free_username_for_github(db, provider_login, provider_user_id)
    user = User(username=username, password_hash=None)
    db.add(user)
    db.commit()
    db.refresh(user)
    _link_github_identity(db, user, provider_user_id, provider_login)
    return _oauth_done(user)


@app.route("/test-login")
def test_login(username: str = ""):
    """CI / Playwright backdoor — creates or reuses a test user.

    Only active when ENABLE_TEST_LOGIN=1.  Never expose in production.

    Query params:
        username  — test account handle (default: playwright_test).
        next      — optional redirect path after login.
    """
    if os.environ.get("ENABLE_TEST_LOGIN", "").lower() not in ("1", "true"):
        abort(404)

    handle = (request.args.get("username") or "playwright_test").strip()[:80]
    db     = get_db_session()
    user   = db.exec(select(User).where(User.username == handle)).first()
    if user is None:
        user = User(username=handle, password_hash=None)
        db.add(user)
        db.commit()
        db.refresh(user)
    _ensure_test_github_identity(db, user, handle)
    session.permanent = True
    login_user(user)
    flash(f"Logged in as {user.username}")
    next_url = request.args.get("next", "")
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return redirect(next_url)
    return redirect(url_for("mealplan"))


@app.route("/api/debug/oauth-identity/<username>")
def debug_oauth_identity(username: str):
    """Return stored GitHub identity for a user — ENABLE_TEST_LOGIN only."""
    if os.environ.get("ENABLE_TEST_LOGIN", "").lower() not in ("1", "true"):
        abort(404)
    db   = get_db_session()
    user = db.exec(select(User).where(User.username == username)).first()
    if user is None:
        return jsonify({"error": "not_found"}), 404
    identity = db.exec(
        select(OAuthIdentity).where(
            OAuthIdentity.user_id == user.id,
            OAuthIdentity.provider == _GITHUB_PROVIDER,
        )
    ).first()
    return jsonify({
        "username":            user.username,
        "has_github_identity": identity is not None,
        "github_id":           identity.provider_user_id if identity else None,
        "provider_user_id":    identity.provider_user_id if identity else None,
        "provider_login":      identity.provider_login if identity else None,
    })


# ---------------------------------------------------------------------------
# Routes — recipes (Sam — CONTRACTS.md §3)
# ---------------------------------------------------------------------------

@app.route("/recipes/search")
def recipes_search():
    """Edamam search + DB upsert (CONTRACTS.md §3, §5).

    Failure codes (all return HTTP 200 with Bootstrap alert):
      timeout          — outbound request exceeds EDAMAM_TIMEOUT seconds
      rate_limited     — HTTP 429 from Edamam
      upstream_error   — other non-2xx (401/403 logged at ERROR)
      upstream_invalid — 2xx but response can't be parsed
    """
    q            = (request.args.get("q") or "").strip()
    recipes      = []
    search_error = None
    featured     = False
    db           = get_db_session()

    if q:
        if not _edamam_configured():
            flash(
                "Recipe search is not configured on this server. "
                "Set EDAMAM_APP_ID and EDAMAM_APP_KEY in .env (see README Team setup).",
                "warning",
            )
            search_error = "not_configured"
        elif session.get("_edamam_rate_limited"):
            flash(
                "Edamam usage limit reached for this app. "
                "Wait until your quota resets (often the next day), then try again.",
                "warning",
            )
            search_error = "rate_limited"
        else:
            recipes, search_error = _edamam_search_recipes(q, db)
            if search_error == "rate_limited":
                session["_edamam_rate_limited"] = True
            if search_error == "timeout":
                flash("Recipe search timeout — please try again.")
            elif search_error == "rate_limited":
                flash(
                    "Edamam usage limit reached for this app. "
                    "Wait until your quota resets (often the next day), then try again. "
                    "Popular picks below use recipes already cached on this server.",
                    "warning",
                )
            elif search_error == "upstream_error":
                flash("The recipe service returned an error. Please try again shortly.")
            elif search_error == "upstream_invalid":
                flash("Could not read recipe results. Please try again.")
    else:
        featured = True
        bootstrap_err = _bootstrap_featured_recipes(db)
        if bootstrap_err == "rate_limited":
            flash(
                "Edamam usage limit reached — showing cached popular recipes only. "
                "Try a new search after your quota resets.",
                "warning",
            )
        recipes = _featured_recipes(db, FEATURED_RECIPE_COUNT)

    return render_template(
        "recipes_search.html",
        title="Discover recipes",
        q=q,
        recipes=recipes,
        search_error=search_error,
        featured=featured,
        show_demo_banner=False,
    )


@app.route("/recipes/<int:recipe_id>")
def recipe_detail(recipe_id: int):
    """Recipe detail — unknown id → 404 per CONTRACTS.md §3."""
    db = get_db_session()
    recipe = db.get(Recipe, recipe_id)
    if recipe is None:
        abort(404)

    ingredients = db.exec(
        select(Ingredient).where(Ingredient.recipe_id == recipe_id)
    ).all()

    return render_template(
        "recipe_detail.html",
        title=recipe.name,
        recipe=recipe,
        ingredients=ingredients,
        demo_preview=False,
    )


@app.route("/recipes/<int:recipe_id>/image")
def recipe_image(recipe_id: int):
    """Same-origin proxy for cached Edamam image URLs (CSP img-src 'self').

    Refreshes stale presigned S3 URLs via Edamam before fetch when possible.
    On upstream failure, performs one Edamam lookup by api_id to renew image_url,
    then retries the fetch.
    """
    db = get_db_session()
    recipe = db.get(Recipe, recipe_id)
    if recipe is None:
        abort(404)

    if not recipe.image_url:
        _refresh_recipe_image_from_edamam(recipe, db)
        if not recipe.image_url:
            abort(404)

    src = recipe.image_url.strip()
    if src.startswith("/"):
        return redirect(src)

    if _s3_presigned_url_is_stale(src):
        refreshed = _refresh_recipe_image_from_edamam(recipe, db)
        if refreshed:
            src = refreshed.strip()

    safe = _safe_remote_image_url(src)
    if not safe:
        abort(404)

    try:
        body, _err_status = _fetch_remote_image(safe)
        if body is not None:
            return body

        # Presigned S3 URLs expire; any upstream failure may mean a stale cache row.
        new_url = _refresh_recipe_image_from_edamam(recipe, db)
        if new_url:
            safe_retry = _safe_remote_image_url(new_url.strip())
            if safe_retry:
                body, _ = _fetch_remote_image(safe_retry)
                if body is not None:
                    return body
    except http.RequestException:
        logger.exception("Image proxy failed for recipe_id=%s", recipe_id)

    abort(502)


@app.route("/recipes/scale", methods=["POST"])
@login_required
@csrf.exempt
def recipes_scale():
    """Scaled ingredient JSON (CONTRACTS.md §3). Auth: required."""
    if not request.is_json:
        return jsonify(error="bad_request", message="Expected Content-Type: application/json"), 400

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="bad_request", message="Invalid JSON body"), 400

    if "recipe_id" not in payload or "target_servings" not in payload:
        return jsonify(error="bad_request", message="Missing recipe_id or target_servings"), 400

    try:
        recipe_id       = int(payload["recipe_id"])
        target_servings = int(payload["target_servings"])
    except (TypeError, ValueError):
        return jsonify(error="bad_request",
                       message="recipe_id and target_servings must be integers"), 400

    if target_servings <= 0:
        return jsonify(error="bad_request",
                       message="target_servings must be greater than zero"), 400

    db = get_db_session()
    recipe = db.get(Recipe, recipe_id)
    if recipe is None:
        return jsonify(error="not_found", message="Recipe not found"), 404

    ingredients = db.exec(
        select(Ingredient).where(Ingredient.recipe_id == recipe_id)
    ).all()

    factor = target_servings / float(recipe.default_servings or 1)

    return jsonify(
        recipe_id=recipe.id,
        target_servings=target_servings,
        default_servings=recipe.default_servings,
        ingredients=[
            {"name": i.name, "quantity": round(i.quantity * factor, 2), "unit": i.unit}
            for i in ingredients
        ],
    )


@app.route("/nutrition/<int:recipe_id>")
def nutrition(recipe_id: int):
    """Scaled macro JSON (CONTRACTS.md §3). Auth: not required."""
    db = get_db_session()
    recipe = db.get(Recipe, recipe_id)
    if recipe is None:
        return jsonify(error="not_found", message="Recipe not found"), 404

    default = float(recipe.default_servings or 1)
    try:
        servings = float(request.args.get("servings", default))
        if servings <= 0:
            servings = default
    except (TypeError, ValueError):
        servings = default

    factor = servings / default

    def _scale(val):
        return round(val * factor, 1) if val is not None else None

    return jsonify(
        recipe_id=recipe.id,
        servings=servings,
        calories=_scale(recipe.calories),
        protein=_scale(recipe.protein),
        carbs=_scale(recipe.carbs),
        fat=_scale(recipe.fat),
    )


# ---------------------------------------------------------------------------
# Routes — meal plan (Sam — CONTRACTS.md §3)
# ---------------------------------------------------------------------------

@app.route("/mealplan", methods=["GET", "POST"])
@login_required
def mealplan():
    """Weekly plan grid; POST upserts one (user, day) row (CONTRACTS.md §3)."""
    if request.method == "POST":
        try:
            day_of_week = int(request.form["day_of_week"])
            recipe_id   = int(request.form["recipe_id"])
            servings    = int(request.form["servings"])
        except (KeyError, TypeError, ValueError):
            flash("Invalid form data.")
            return redirect(url_for("mealplan"))

        if not (0 <= day_of_week <= 6) or servings <= 0:
            flash("Invalid day or servings value.")
            return redirect(url_for("mealplan"))

        db = get_db_session()
        if db.get(Recipe, recipe_id) is None:
            flash("Recipe not found.")
            return redirect(url_for("mealplan"))

        existing = db.exec(
            select(MealPlan).where(
                MealPlan.user_id == current_user.id,
                MealPlan.day_of_week == day_of_week,
            )
        ).first()

        if existing:
            existing.recipe_id = recipe_id
            existing.servings  = servings
            db.add(existing)
        else:
            db.add(MealPlan(
                user_id=current_user.id,
                day_of_week=day_of_week,
                recipe_id=recipe_id,
                servings=servings,
            ))
        db.commit()
        flash("Meal plan updated.")
        return redirect(url_for("mealplan"))

    # GET — single joined query instead of N+1 per-day recipe lookups
    db = get_db_session()
    rows = db.exec(
        select(MealPlan, Recipe)
        .join(Recipe, MealPlan.recipe_id == Recipe.id)
        .where(MealPlan.user_id == current_user.id)
    ).all()

    planned = {}
    for mp, recipe in rows:
        planned[mp.day_of_week] = {
            "recipe_id": mp.recipe_id,
            "servings":  mp.servings,
            "name":      recipe.name,
            "image_url": recipe.image_url,
        }

    return render_template("mealplan.html", title="Meal plan", planned=planned)


@app.route("/mealplan/<int:day>", methods=["DELETE"])
@login_required
def mealplan_clear_day(day: int):
    """Clear one day's entry (CONTRACTS.md §3). 404 if nothing planned."""
    db = get_db_session()
    row = db.exec(
        select(MealPlan).where(
            MealPlan.user_id == current_user.id,
            MealPlan.day_of_week == day,
        )
    ).first()

    if row is None:
        abort(404)

    db.delete(row)
    db.commit()

    accept = request.headers.get("Accept", "")
    if "application/json" in accept:
        return jsonify(ok=True, day=day)

    flash("Day cleared.")
    return redirect(url_for("mealplan"))


@app.route("/mealplan/recipe-suggest")
def mealplan_recipe_suggest():
    """JSON typeahead — returns up to 20 recipes matching query string `q`."""
    if not current_user.is_authenticated:
        return jsonify(recipes=[]), 401

    q    = (request.args.get("q") or "").strip().lower()
    db   = get_db_session()
    stmt = select(Recipe).where(Recipe.api_id.not_like("demo.p%"))  # type: ignore[arg-type]
    if q:
        stmt = stmt.where(func.lower(Recipe.name).contains(q))
    rows = db.exec(stmt.limit(20)).all()

    return jsonify(recipes=[
        {
            "id": r.id,
            "name": r.name,
            "image_url": _public_recipe_image_url(r.id, r.image_url) or "",
        }
        for r in rows
    ])


# ---------------------------------------------------------------------------
# Schema creation / Week 7 upgrades (Justin owns formal migrations — CONTRACTS.md §12)
# ---------------------------------------------------------------------------

def _upgrade_week7_auth_schema() -> None:
    """Bridge patch until Justin's Alembic migration (CONTRACTS.md §1, §12).

    create_all() does not ALTER existing Postgres volumes — Week 7 needs nullable
    password_hash and GitHub columns on users plus oauth_identities.
    Skips entirely when the schema is already up to date.
    """
    insp = inspect(engine)
    if "users" not in insp.get_table_names():
        return
    user_cols = {c["name"]: c for c in insp.get_columns("users")}
    user_col_names = set(user_cols)

    pw = user_cols.get("password_hash")
    pw_needs_fix = pw is not None and not pw.get("nullable", True)
    needs_github_id = "github_id" not in user_col_names
    needs_github_login = "github_id" in user_col_names and "github_login" not in user_col_names

    if not pw_needs_fix and not needs_github_id and not needs_github_login:
        return

    dialect = engine.dialect.name
    with engine.begin() as conn:
        if pw_needs_fix:
            conn.execute(text("ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL"))

        if needs_github_id:
            if dialect == "postgresql":
                conn.execute(text(
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS github_id VARCHAR(64)"
                ))
                conn.execute(text(
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS github_login VARCHAR(255)"
                ))
                conn.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_github_id "
                    "ON users (github_id) WHERE github_id IS NOT NULL"
                ))
            else:
                conn.execute(text("ALTER TABLE users ADD COLUMN github_id VARCHAR(64)"))
                conn.execute(text(
                    "ALTER TABLE users ADD COLUMN github_login VARCHAR(255)"
                ))
        elif needs_github_login:
            if dialect == "postgresql":
                conn.execute(text(
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS github_login VARCHAR(255)"
                ))
            else:
                conn.execute(text(
                    "ALTER TABLE users ADD COLUMN github_login VARCHAR(255)"
                ))

        # Week 5 volumes: created_at is NOT NULL but often has no DB default.
        # OAuth/register inserts must not rely on server_default alone.
        if "created_at" in user_col_names:
            created_at_col = user_cols["created_at"]
            if created_at_col.get("default") is None:
                if dialect == "postgresql":
                    conn.execute(text(
                        "ALTER TABLE users ALTER COLUMN created_at "
                        "SET DEFAULT CURRENT_TIMESTAMP"
                    ))
                else:
                    conn.execute(text(
                        "UPDATE users SET created_at = CURRENT_TIMESTAMP "
                        "WHERE created_at IS NULL"
                    ))


def _upgrade_recipe_image_url_length() -> None:
    """Widen image_url for long Edamam presigned URLs (Postgres volumes from Week 6/7)."""
    insp = inspect(engine)
    if "recipes" not in insp.get_table_names():
        return
    if engine.dialect.name != "postgresql":
        return
    cols = {c["name"]: c for c in insp.get_columns("recipes")}
    col = cols.get("image_url")
    if col is None:
        return
    length = getattr(col["type"], "length", None)
    if length is not None and length < 2048:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE recipes ALTER COLUMN image_url TYPE VARCHAR(2048)"))


SQLModel.metadata.create_all(engine)
_upgrade_week7_auth_schema()
_upgrade_recipe_image_url_length()
with engine.begin() as conn:
    _sync_recipes_id_sequence(conn)
_purge_legacy_placeholder_demos()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
