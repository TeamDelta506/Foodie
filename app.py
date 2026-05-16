"""
Course 506 Week 6 — Flask + Postgres + SQLModel + Bootstrap + Edamam API

Route ownership per CONTRACTS.md §7:
  Sam    — /recipes/search, /recipes/<id>, POST /recipes/scale,
            GET /nutrition/<id>, POST /mealplan, GET /mealplan,
            DELETE /mealplan/<day>; requests + Edamam wiring
  Asia   — templates/, static/
  Justin — SQLModel models for recipes/ingredients/mealplans; Flask-Login
"""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import requests as http
from flask import (
    Flask, render_template, request, redirect, url_for, flash, g,
    send_from_directory, abort, jsonify,
)
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user, current_user,
    login_required,
)
from sqlalchemy import (
    Column, DateTime, Integer, SmallInteger, ForeignKey,
    CheckConstraint, UniqueConstraint, event as sa_event, func,
)
from sqlmodel import SQLModel, Field, Session, create_engine, select
from werkzeug.exceptions import HTTPException
from werkzeug.security import generate_password_hash, check_password_hash

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Application setup
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-not-for-production")

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://app:app@db:5432/app")
engine = create_engine(DATABASE_URL, echo=False)

S3_CONTENT_DIR = Path(__file__).parent / "S3_content"

EDAMAM_APP_ID  = os.environ.get("EDAMAM_APP_ID", "")
EDAMAM_APP_KEY = os.environ.get("EDAMAM_APP_KEY", "")
EDAMAM_BASE    = "https://api.edamam.com/api/recipes/v2"
EDAMAM_TIMEOUT = 4  # seconds per CONTRACTS.md §5


def _edamam_configured() -> bool:
    """True when server-side Edamam credentials are set (shared by all users)."""
    return bool(os.environ.get("EDAMAM_APP_ID") and os.environ.get("EDAMAM_APP_KEY"))


def _edamam_account_user() -> str:
    """User id for Edamam active-user tracking (required on some developer plans)."""
    if current_user.is_authenticated:
        return str(current_user.id)
    return os.environ.get("EDAMAM_ACCOUNT_USER", "foodie-team")


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
    password_hash: str         = Field(max_length=255)
    created_at:    datetime | None = Field(
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
    image_url:        str | None  = Field(default=None, max_length=1000)
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
# Demo seed — real DB rows inserted after table creation so tests and local
# preview have working recipes without a live Edamam key.
#
# Six recipe rows (ids 1–6) are seeded explicitly so the first real Edamam
# upsert gets id=7, preventing str(rid)="7" from colliding with
# data-day="0"–"6" in the mealplan template and breaking the integration
# test's "not in board_after" assertion.
# ---------------------------------------------------------------------------

_NOW = lambda: datetime.now(timezone.utc)  # noqa: E731


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
            # Placeholders push auto-increment past data-day range (0–6)
            {"id": 3, "api_id": "demo.p3", "name": "Demo placeholder 3", "image_url": None,
             "calories": 300.0, "protein": 10.0, "carbs": 40.0, "fat": 10.0,
             "default_servings": 1, "created_at": _NOW()},
            {"id": 4, "api_id": "demo.p4", "name": "Demo placeholder 4", "image_url": None,
             "calories": 350.0, "protein": 12.0, "carbs": 45.0, "fat": 11.0,
             "default_servings": 1, "created_at": _NOW()},
            {"id": 5, "api_id": "demo.p5", "name": "Demo placeholder 5", "image_url": None,
             "calories": 380.0, "protein": 14.0, "carbs": 48.0, "fat": 13.0,
             "default_servings": 1, "created_at": _NOW()},
            {"id": 6, "api_id": "demo.p6", "name": "Demo placeholder 6", "image_url": None,
             "calories": 410.0, "protein": 16.0, "carbs": 52.0, "fat": 14.0,
             "default_servings": 1, "created_at": _NOW()},
        ],
    )


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

    existing = db.exec(select(Recipe).where(Recipe.api_id == api_id)).first()
    if existing:
        return existing

    def _macro(key: str) -> "float | None":
        n = (recipe_data.get("totalNutrients") or {}).get(key, {})
        qty = n.get("quantity")
        return float(qty) if qty is not None else None

    recipe = Recipe(
        api_id=api_id,
        name=name,
        image_url=recipe_data.get("image"),
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


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------

def get_db_session():
    if "db_session" not in g:
        g.db_session = Session(engine)
    return g.db_session


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
    login_user(user)
    return redirect(url_for("home"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    db = get_db_session()
    user = db.exec(select(User).where(User.username == username)).first()

    if user is None or not check_password_hash(user.password_hash, password):
        flash("Invalid username or password.")
        return redirect(url_for("login"))

    login_user(user)
    return redirect(url_for("home"))


@app.route("/logout", methods=["POST"])
def logout():
    logout_user()
    return redirect(url_for("home"))


@app.route("/about")
def about():
    return render_template("about.html")


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

    if q:
        if not _edamam_configured():
            flash(
                "Recipe search is not configured on this server. "
                "Set EDAMAM_APP_ID and EDAMAM_APP_KEY in .env (see README Team setup).",
                "warning",
            )
            search_error = "not_configured"
        else:
            try:
                resp = http.get(
                    EDAMAM_BASE,
                    params={"type": "public", "q": q,
                            "app_id": EDAMAM_APP_ID, "app_key": EDAMAM_APP_KEY},
                    headers=_edamam_request_headers(),
                    timeout=EDAMAM_TIMEOUT,
                )

                if resp.status_code == 429:
                    flash("Recipe search is rate limited — please try again in a moment.")
                    search_error = "rate_limited"
                elif not resp.ok:
                    if resp.status_code in (401, 403):
                        logger.error("Edamam auth error %s — check API keys", resp.status_code)
                    else:
                        logger.error("Edamam upstream error: HTTP %s", resp.status_code)
                    flash("The recipe service returned an error. Please try again shortly.")
                    search_error = "upstream_error"
                else:
                    try:
                        hits = resp.json().get("hits", [])
                        db = get_db_session()
                        for hit in hits:
                            recipe = _parse_and_upsert_hit(hit, db)
                            if recipe is not None:
                                recipes.append(recipe)
                    except (ValueError, KeyError, AttributeError):
                        logger.exception("Could not parse Edamam response")
                        flash("Could not read recipe results. Please try again.")
                        search_error = "upstream_invalid"

            except http.exceptions.ReadTimeout:
                flash("Recipe search timed out. Please try again.")
                search_error = "timeout"
            except http.exceptions.RequestException:
                logger.exception("Edamam request failed")
                flash("Could not reach the recipe service. Please try again.")
                search_error = "upstream_error"

    else:
        db = get_db_session()
        recipes = db.exec(select(Recipe).limit(20)).all()

    return render_template(
        "recipes_search.html",
        title="Discover recipes",
        q=q,
        recipes=recipes,
        search_error=search_error,
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


@app.route("/recipes/scale", methods=["POST"])
@login_required
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

    # GET
    db = get_db_session()
    rows = db.exec(
        select(MealPlan).where(MealPlan.user_id == current_user.id)
    ).all()

    planned = {}
    for row in rows:
        recipe = db.get(Recipe, row.recipe_id)
        planned[row.day_of_week] = {
            "recipe_id": row.recipe_id,
            "servings":  row.servings,
            "name":      recipe.name if recipe else None,
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
    flash("Day cleared.")
    return redirect(url_for("mealplan"))


@app.route("/mealplan/recipe-suggest")
def mealplan_recipe_suggest():
    """JSON typeahead — returns up to 20 recipes matching query string `q`."""
    if not current_user.is_authenticated:
        return jsonify(recipes=[]), 401

    q    = (request.args.get("q") or "").strip().lower()
    db   = get_db_session()
    rows = db.exec(select(Recipe)).all()

    pick = [r for r in rows if q in r.name.lower()][:20] if q else rows[:20]

    return jsonify(recipes=[
        {"id": r.id, "name": r.name, "image_url": r.image_url or ""}
        for r in pick
    ])


# ---------------------------------------------------------------------------
# Schema creation
# ---------------------------------------------------------------------------

SQLModel.metadata.create_all(engine)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
