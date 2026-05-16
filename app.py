"""
Course 506 Week 5 Skeleton — Flask + Postgres + SQLModel + Bootstrap

Single-file Flask app demonstrating the architecture of a web application:
- Server (Flask) handles HTTP requests
- Database (Postgres via SQLModel) stores user state across requests
- Sessions (Flask sessions) keep users logged in across requests
- Templates render HTML to send back to the browser

The home page serves the static site you sync from your S3 bucket into
S3_content/. Login, register, logout, and about are Flask-rendered routes.

This file is meant to be readable top-to-bottom. No Blueprints, no app factory,
no advanced Flask patterns. Just enough to teach the architecture.

---------------------------------------------------------------------------
CONTRACTS.md (Week 6) — route ownership vs. what lives in this file
---------------------------------------------------------------------------
- Section 3 defines **required URL behavior** (search, detail, scale JSON,
  meal plan, nutrition JSON, etc.). The contract cares that those paths behave
  as specified, not which teammate's PR introduced the first draft.
- Section 7 assigns **Sam** to own **Edamam + requests**, the Week 6 server
  routes in this file, and ``tests/test_server_edamam_routes.py``. **Justin**
  owns SQLModel tables for recipes/ingredients/mealplans; **Asia** owns
  templates and static assets.

**Handoff:** Demo data, ``POST /recipes/scale``, branded ``HTTPException``
pages, and meal-plan GET/suggest stubs were added so templates and tests can
run. That overlaps Sam's lane for **implementation**—**coordinate on merge**
(or let Sam supersede in a follow-up). Blocks below marked **SAM:** are the
intended replace points: Edamam (section 5), DB upsert by ``api_id``, timeouts
and error-to-flash mapping on search, ``POST /mealplan``, ``DELETE /mealplan/<day>``,
``GET /nutrition/<id>``, and swapping demo helpers for real SQLModel queries
once Justin's schema is available.
"""

import os
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

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
    CheckConstraint, UniqueConstraint, func,
)
from sqlmodel import SQLModel, Field, Session, create_engine, select
from werkzeug.exceptions import HTTPException
from werkzeug.security import generate_password_hash, check_password_hash

# ---------------------------------------------------------------------------
# DEMO: in-memory sample recipes for UI preview (search cards + detail + meal
# plan typeahead). Remove once the team serves real rows from `recipes`.
# Set DEMO_MOCK_RECIPES_ENABLED = False to hide demos without deleting code.
#
# Mock images: files in static/img/demo/ (served at /static/img/demo/...).
# ---------------------------------------------------------------------------
DEMO_MOCK_RECIPES_ENABLED = True

_IMG_BOWL = "/static/img/demo/bowl.jpg"
_IMG_SALMON = "/static/img/demo/salmon.jpg"


def _demo_recipe_summaries():
    """Minimal rows for Discover cards + meal-plan typeahead source (until DB)."""
    return [
        SimpleNamespace(id=1, name="Garden grain bowl", image_url=_IMG_BOWL, calories=420.0),
        SimpleNamespace(id=2, name="Citrus herb salmon", image_url=_IMG_SALMON, calories=560.0),
    ]


def _demo_recipe_detail(recipe_id: int):
    """Full recipe + ingredients for /recipes/<id> preview. Returns (recipe, ingredients)."""
    demos = {
        1: (
            SimpleNamespace(
                id=1,
                name="Garden grain bowl",
                image_url=_IMG_BOWL,
                default_servings=2,
                calories=420.0,
                protein=18.0,
                carbs=55.0,
                fat=12.0,
            ),
            [
                SimpleNamespace(name="Quinoa", quantity=1.0, unit="cup"),
                SimpleNamespace(name="Kale", quantity=2.0, unit="cup"),
                SimpleNamespace(name="Lemon juice", quantity=2.0, unit="tbsp"),
            ],
        ),
        2: (
            SimpleNamespace(
                id=2,
                name="Citrus herb salmon",
                image_url=_IMG_SALMON,
                default_servings=4,
                calories=560.0,
                protein=48.0,
                carbs=8.0,
                fat=32.0,
            ),
            [
                SimpleNamespace(name="Salmon fillet", quantity=1.5, unit="lb"),
                SimpleNamespace(name="Fresh dill", quantity=2.0, unit="tbsp"),
                SimpleNamespace(name="Orange zest", quantity=1.0, unit="tsp"),
            ],
        ),
    }
    return demos.get(recipe_id, (None, []))


def _scale_recipe_ingredients(recipe_id: int, target_servings: int):
    """Return (recipe, scaled_ingredient_dicts) or (None, None) if recipe unknown.

    SAM: Replace body with DB-backed ingredients + CONTRACTS.md §3 scale math
    (factor = target_servings / default_servings; round quantities server-side).
    """
    recipe, ingredients = _demo_recipe_detail(recipe_id)
    if recipe is None:
        return None, None
    default = float(recipe.default_servings)
    if default <= 0:
        return None, None
    factor = target_servings / default
    scaled = []
    for ing in ingredients:
        qty = round(float(ing.quantity) * factor, 2)
        scaled.append({"name": ing.name, "quantity": qty, "unit": ing.unit})
    return recipe, scaled


# ---------------------------------------------------------------------------
# Application setup
# ---------------------------------------------------------------------------

app = Flask(__name__)

# Secret key signs the session cookie so users can't tamper with it.
# In production this comes from an environment variable and is a long random string.
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-not-for-production")

# Database URL. Postgres runs in a separate container; the URL points there.
# For local testing without Docker, override with sqlite:
#   DATABASE_URL=sqlite:///dev.db python app.py
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://app:app@db:5432/app")

# SQLModel uses SQLAlchemy underneath. The engine is the connection pool.
engine = create_engine(DATABASE_URL, echo=False)

# Path to the synced S3 content. Students populate this with `aws s3 sync`.
S3_CONTENT_DIR = Path(__file__).parent / "S3_content"

# Flask-Login setup
login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.init_app(app)
app.extensions["login_manager"] = login_manager


# ---------------------------------------------------------------------------
# Database model
# ---------------------------------------------------------------------------

class User(UserMixin, SQLModel, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True, max_length=80)
    password_hash: str = Field(max_length=255)
    created_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=func.now()),
    )


class Recipe(SQLModel, table=True):
    __tablename__ = "recipes"
    __table_args__ = (
        CheckConstraint("default_servings > 0", name="ck_recipes_default_servings"),
    )

    id: int | None = Field(default=None, primary_key=True)
    api_id: str = Field(unique=True, index=True, max_length=255)
    name: str = Field(max_length=500)
    image_url: str | None = Field(default=None, max_length=1000)
    calories: float | None = Field(default=None)
    protein: float | None = Field(default=None)
    carbs: float | None = Field(default=None)
    fat: float | None = Field(default=None)
    default_servings: int = Field()
    created_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=func.now()),
    )


class Ingredient(SQLModel, table=True):
    __tablename__ = "ingredients"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_ingredients_quantity"),
    )

    id: int | None = Field(default=None, primary_key=True)
    recipe_id: int = Field(
        sa_column=Column(Integer, ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False)
    )
    name: str = Field(max_length=300)
    quantity: float = Field()
    unit: str = Field(max_length=50)


class MealPlan(SQLModel, table=True):
    __tablename__ = "mealplans"
    __table_args__ = (
        UniqueConstraint("user_id", "day_of_week", name="uq_mealplans_user_day"),
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_mealplans_day_of_week"),
        CheckConstraint("servings > 0", name="ck_mealplans_servings"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(
        sa_column=Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    )
    day_of_week: int = Field(
        sa_column=Column(SmallInteger, nullable=False)
    )
    recipe_id: int = Field(
        sa_column=Column(Integer, ForeignKey("recipes.id", ondelete="RESTRICT"), nullable=False)
    )
    servings: int = Field()


# ---------------------------------------------------------------------------
# Session helper
#
# SQLModel doesn't have a Flask extension. We open a fresh DB session for each
# request and close it when the request finishes. Flask's `g` object holds
# request-scoped state.
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


# Make `user` available in every Flask-rendered template (login, register,
# about, recipes, meal plan). Static files served from S3_content/ don't use
# Jinja2, so this only affects Flask-rendered pages.
@app.context_processor
def inject_user():
    return {"user": current_user if current_user.is_authenticated else None}


@app.errorhandler(HTTPException)
def handle_http_exception(e: HTTPException):
    """Branded HTML for HTTP errors (404, 403, 405, 5xx, …) using the same shell as home.

    Not listed under Sam’s route table in CONTRACTS.md §7 — shared app UX.
    SAM: If JSON-only routes must return JSON errors instead of HTML for some
    paths, register a narrower handler or check ``request.is_json`` / Accept
    here and delegate before rendering ``error.html``.
    """
    code = e.code or 500
    desc = (e.description or "").strip()

    if code == 404:
        page_title = "Page not found — Foodie"
        heading = "We can't find that page"
        lead = "The address may be mistyped, or the recipe or page may no longer be here."
    elif code == 403:
        page_title = "Access denied — Foodie"
        heading = "You can't open this"
        lead = desc or "You don't have permission to view this resource. Try signing in with a different account."
    elif code == 405:
        page_title = "Method not allowed — Foodie"
        heading = "That action isn't supported here"
        lead = desc or "Use the navigation or buttons on a Foodie page instead of this address."
    elif code >= 500:
        page_title = "Something went wrong — Foodie"
        heading = "Server hiccup"
        lead = "Please try again in a moment. If the problem continues, come back later."
    else:
        page_title = "Request problem — Foodie"
        heading = "We couldn't complete that request"
        lead = desc or "Try going back, or use the shortcuts below."

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
# Routes — optional synced static site under /site/
#
# Populate S3_content/ with:  aws s3 sync s3://<your-bucket>/ S3_content/
# If index.html is missing, /site/ redirects to the Foodie home page.
#
# The Flask home page is the primary entry: recipes, meal plan, about, auth.
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
# Routes — authentication (Flask-rendered, not static)
# ---------------------------------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    # POST: create a new user.
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    if not username or not password:
        flash("Username and password are required.")
        return redirect(url_for("register"))

    db = get_db_session()
    existing = db.exec(select(User).where(User.username == username)).first()
    if existing is not None:
        flash("That username is already taken.")
        return redirect(url_for("register"))

    user = User(
        username=username,
        password_hash=generate_password_hash(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    login_user(user)
    return redirect(url_for("home"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    # POST: validate credentials.
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
    # Each team replaces this content with their own About page (see
    # the assignment instructions in README.md).
    return render_template("about.html")


# ---------------------------------------------------------------------------
# Week 6 — Recipes & meal plan (CONTRACTS.md §3)
#
# SAM (per §7): You own production behavior here — Edamam ``requests`` (§5),
# timeouts, error → flash codes on search, DB upsert by ``api_id``, and any
# routes still stubbed elsewhere (e.g. ``POST /mealplan``, ``DELETE /mealplan/<day>``,
# ``GET /nutrition/<id>``). The blocks below are scaffolding so Asia’s templates
# and coordinator tests can run until your integration lands; replace demo
# branches rather than deleting template contracts.
# ---------------------------------------------------------------------------


@app.route("/recipes/search")
def recipes_search():
    """SAM: Edamam search + upsert (§3, §5); map timeout/rate_limit/upstream_* to flash."""
    q = (request.args.get("q") or "").strip()
    recipes = []
    if DEMO_MOCK_RECIPES_ENABLED and not q and not recipes:
        recipes = _demo_recipe_summaries()
    return render_template(
        "recipes_search.html",
        title="Discover recipes",
        q=q,
        recipes=recipes,
        search_error=None,
        show_demo_banner=DEMO_MOCK_RECIPES_ENABLED and bool(recipes) and not q,
    )


@app.route("/recipes/<int:recipe_id>")
def recipe_detail(recipe_id: int):
    """SAM: Load cached recipe by ``recipes.id``; unknown id → 404 (CONTRACTS.md §3)."""
    recipe, ingredients = None, []
    demo_preview = False
    if DEMO_MOCK_RECIPES_ENABLED:
        recipe, ingredients = _demo_recipe_detail(recipe_id)
        demo_preview = recipe is not None
    return render_template(
        "recipe_detail.html",
        title=(recipe.name if recipe else "Recipe"),
        recipe=recipe,
        ingredients=ingredients,
        demo_preview=demo_preview,
    )


@app.route("/recipes/scale", methods=["POST"])
@login_required
def recipes_scale():
    """CONTRACTS.md §3 ``POST /recipes/scale`` — JSON scale (auth: session today).

    SAM: Keep request/response envelope; read default_servings + ingredients from
    DB (Justin schema), not ``_scale_recipe_ingredients`` / demo dict.
    """

    if not request.is_json:
        return (
            jsonify(error="bad_request", message="Expected Content-Type: application/json"),
            400,
        )

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="bad_request", message="Invalid JSON body"), 400

    if "recipe_id" not in payload or "target_servings" not in payload:
        return (
            jsonify(error="bad_request", message="Missing recipe_id or target_servings"),
            400,
        )

    try:
        recipe_id = int(payload["recipe_id"])
        target_servings = int(payload["target_servings"])
    except (TypeError, ValueError):
        return (
            jsonify(error="bad_request", message="recipe_id and target_servings must be integers"),
            400,
        )

    if target_servings <= 0:
        return jsonify(error="bad_request", message="target_servings must be greater than zero"), 400

    if not DEMO_MOCK_RECIPES_ENABLED:
        return jsonify(error="not_found", message="Recipe not found"), 404

    recipe, ingredients = _scale_recipe_ingredients(recipe_id, target_servings)
    if recipe is None:
        return jsonify(error="not_found", message="Recipe not found"), 404

    return jsonify(
        recipe_id=recipe.id,
        target_servings=target_servings,
        default_servings=recipe.default_servings,
        ingredients=ingredients,
    )


@app.route("/mealplan", methods=["GET"])
@login_required
def mealplan():
    """SAM: Add ``POST`` on this path (upsert §3); pass ``planned`` dict keyed by weekday."""
    return render_template(
        "mealplan.html",
        title="Meal plan",
        planned={},
    )


def _mealplan_suggest_source_rows():
    """Recipes considered for meal-plan typeahead. Sam: query `recipes` with LIMIT + ILIKE."""
    if DEMO_MOCK_RECIPES_ENABLED:
        return _demo_recipe_summaries()
    return []


@app.route("/mealplan/recipe-suggest")
def mealplan_recipe_suggest():
    """SAM: Keep JSON shape; source rows from ``recipes`` (ILIKE), not demo list."""
    """JSON for meal-plan recipe picker (scalable: swap source for DB / Edamam cache)."""
    if not current_user.is_authenticated:
        return jsonify(recipes=[]), 401
    q_raw = (request.args.get("q") or "").strip()
    q = q_raw.lower()
    rows = _mealplan_suggest_source_rows()
    if not q:
        pick = rows[:20]
    else:
        pick = [r for r in rows if q in r.name.lower() or q_raw == str(r.id)][:20]
    out = [
        {
            "id": r.id,
            "name": r.name,
            "image_url": getattr(r, "image_url", None) or "",
        }
        for r in pick
    ]
    return jsonify(recipes=out)


# ---------------------------------------------------------------------------
# First-run schema creation
# ---------------------------------------------------------------------------

# In production you'd use a migration tool (Alembic) instead.
# For Week 5, this is enough — it creates tables if they don't exist.
SQLModel.metadata.create_all(engine)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
