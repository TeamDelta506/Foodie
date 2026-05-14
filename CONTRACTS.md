# Foodie — CONTRACTS.md

**Team:** TeamDelta506  
**Project:** Foodie — Recipe Scaler & Meal Planner  
**Week:** 6  
**Coordinator:** Sowmya Korasikha  
**Last updated:** Wednesday, May 13, 2026 (PDT) — post–LLM session

This document is the team’s binding agreement for Week 6. Routes, tables, JSON envelopes, and failure semantics live here. When code disagrees with this file, **fix the code** unless the team agrees to revise the contract (small follow-up PR: `"Contract revision: <reason>"`).

---

## 1. Schema

### Table: `users` (skeleton — carried forward)

Matches the Week 5 starter. **Db-and-security** may refactor session auth to Flask-Login; columns stay the same unless the team opens a contract revision.

| Column | Type | Constraints / notes |
|--------|------|------------------------|
| `id` | `INTEGER` | `PRIMARY KEY`, autoincrement |
| `username` | `VARCHAR(80)` | `UNIQUE NOT NULL`, indexed |
| `password_hash` | `VARCHAR(255)` | `NOT NULL` (Werkzeug hash) |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | `NOT NULL`, default now (UTC) |

---

### Table: `recipes` (new — global Edamam cache)

**Decision:** Shared cache keyed by Edamam’s recipe identity. **No `user_id`** — “saving a recipe” in the About pitch means **add to meal plan** in Week 6, not a private favorites list (see §6).

| Column | Type | Constraints / notes |
|--------|------|------------------------|
| `id` | `INTEGER` | `PRIMARY KEY`, autoincrement — **this is `<id>` in URLs** |
| `api_id` | `VARCHAR(255)` | `UNIQUE NOT NULL` — Edamam’s stable recipe id / URI fragment used for upsert |
| `name` | `VARCHAR(500)` | `NOT NULL` |
| `image_url` | `VARCHAR(1000)` | nullable |
| `calories` | `DOUBLE PRECISION` | nullable if upstream omits |
| `protein` | `DOUBLE PRECISION` | grams; nullable if omitted |
| `carbs` | `DOUBLE PRECISION` | grams; nullable if omitted |
| `fat` | `DOUBLE PRECISION` | grams; nullable if omitted |
| `default_servings` | `INTEGER` | `NOT NULL`, `CHECK (default_servings > 0)` — **baseline for scaling** (from Edamam `yield` / servings when available; else `1`) |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | `NOT NULL`, default now (UTC) |

**Indexes:** at minimum `INDEX` on `api_id` (unique already covers lookup).

**Caching policy (Week 6):** insert-or-update on search/detail **by `api_id`**. Rows are **not** refreshed from Edamam after first insert (deliberate — see §6).

---

### Table: `ingredients` (new)

Normalized ingredient lines for a cached recipe.

| Column | Type | Constraints / notes |
|--------|------|------------------------|
| `id` | `INTEGER` | `PRIMARY KEY` |
| `recipe_id` | `INTEGER` | `NOT NULL`, `REFERENCES recipes(id) ON DELETE CASCADE` |
| `name` | `VARCHAR(300)` | `NOT NULL` |
| `quantity` | `DOUBLE PRECISION` | `NOT NULL`, `CHECK (quantity >= 0)` |
| `unit` | `VARCHAR(50)` | `NOT NULL` — e.g. `g`, `cup`, `whole` |

---

### Table: `mealplans` (new)

**Decision:** **One row per `(user_id, day_of_week)`** — at most **one planned meal per calendar day** per user for Week 6. Breakfast/lunch/dinner slots are **out of scope** until a future week (see §6).

| Column | Type | Constraints / notes |
|--------|------|------------------------|
| `id` | `INTEGER` | `PRIMARY KEY` |
| `user_id` | `INTEGER` | `NOT NULL`, `REFERENCES users(id) ON DELETE CASCADE` |
| `day_of_week` | `SMALLINT` | `NOT NULL`, **`CHECK (day_of_week BETWEEN 0 AND 6)`** — **0 = Monday … 6 = Sunday** (matches Python `date.weekday()`) |
| `recipe_id` | `INTEGER` | `NOT NULL`, `REFERENCES recipes(id)` — **`ON DELETE RESTRICT`** (prevent deleting a recipe that’s still planned; contract for Week 6) |
| `servings` | `INTEGER` | `NOT NULL`, `CHECK (servings > 0)` — planned servings for that day |

**Uniqueness:** `UNIQUE (user_id, day_of_week)`.

---

## 2. Identifier semantics

- **`/recipes/<id>`**, **`/nutrition/<id>`**, and meal-plan pointers all use **`recipes.id`** (integer PK).
- Edamam **`api_id`** is **internal only** (dedupe + ingestion). Canonical user-facing URLs **never** embed the opaque Edamam string.

---

## 3. Endpoint contracts

**Stack assumptions:** HTML responses use the Bootstrap patterns from the Week 5 skeleton unless noted. JSON responses use `Content-Type: application/json`.

**Error envelope (JSON routes only):**  

```json
{ "error": "<machine_code|null>", "message": "<human text>" }
```

On success, `error` is JSON `null` **or** the key is omitted — pick one style app-wide; tests accept either if documented here: **use `"error": null` on success** for `/nutrition` only; meal-scale JSON uses the same envelope for validation errors.

Global flash messages (HTML): use Flask `flash()`; failures on otherwise-valid pages keep **HTTP 200** when the contract says so (search page).

---

### `GET /recipes/search`

**Purpose:** Search recipes via Edamam; upsert matches into `recipes`; render HTML list + search form.

**Auth:** **Not required** (anonymous discovery).

**Query params:**

| Param | Required | Description |
|--------|----------|-------------|
| `q` | No | Free text. If missing/blank, show empty state + any optional popular/recent cached rows (implementation choice — if unused, show friendly empty state). |

**Upstream:** Edamam Recipe Search API `GET /api/recipes/v2` — see §5.

**Success:** `200` HTML. Page **must** include a `GET` form with `action` pointing at `/recipes/search` and an input named **`q`**.

**Failure (Edamam unavailable):** Still **`200` HTML** with a **visible Bootstrap alert** (flash or equivalent) describing the issue. **Four** user-facing failure codes map to copy:

| Code | When |
|------|------|
| `timeout` | Outbound request exceeds **4s** |
| `rate_limited` | HTTP **429** from Edamam |
| `upstream_error` | Other non-2xx **including 401/403** (mis-keys are ops issues — log at **ERROR** server-side) |
| `upstream_invalid` | 2xx but payload can’t be parsed / doesn’t match expected shape |

**Note:** 401/403 are **not** a separate user-facing code — they fold into `upstream_error` **with server-side logging**.

Partial local matches: if upstream fails, page may still list **cached** `recipes` whose `name` matches `q` (case-insensitive substring). Contract does **not** require this, but allows it (“degrade gracefully”).

---

### `GET /recipes/<id>`

**Purpose:** Recipe detail view (image, macros, ingredient table, links to planner actions).

**Auth:** **Not required.**

**Success:** `200` HTML for valid cached `id`.

**Errors:**

| Condition | Status | Behavior |
|------------|--------|-----------|
| Unknown `id` | `404` | Generic not-found page or skeleton 404 |

---

### `POST /recipes/scale`

**Purpose:** Return scaled ingredient quantities for a cached recipe.

**Auth:** **Required** — login session or Flask-Login equivalent.

**Request:** `Content-Type: application/json`

```json
{
  "recipe_id": 123,
  "target_servings": 6
}
```

**Success:** `200` JSON

```json
{
  "recipe_id": 123,
  "target_servings": 6,
  "default_servings": 2,
  "ingredients": [
    { "name": "rice", "quantity": 1.5, "unit": "cup" }
  ]
}
```

**Scale math:** `factor = target_servings / default_servings`; each stored ingredient quantity is multiplied by `factor`; round **display** to a reasonable precision (e.g. 2 decimal places) server-side.

**Errors:**

| Condition | Status | Body |
|------------|--------|------|
| Not authenticated | `302` → login | *(HTML)* |
| Bad JSON / missing keys | `400` JSON envelope |
| Unknown `recipe_id` | `404` JSON envelope |
| `target_servings` ≤ 0 | `400` JSON envelope |

---

### `GET /nutrition/<id>?servings=N`

**Purpose:** Return **scaled** macronutrition for a **cached** recipe. **Differs from detail page:** JSON-only; scaled by `servings` (if omitted, use **`default_servings`** from the row).

**Auth:** **Not required.**

**Query params:**

| Param | Required | Description |
|--------|----------|-------------|
| `servings` | No | Positive number. If absent, treat as `default_servings`. |

**Success:** `200` JSON

```json
{
  "recipe_id": 123,
  "servings": 4,
  "calories": 920,
  "protein": 42,
  "carbs": 80,
  "fat": 30
}
```

Values are **totals for the requested `servings`**, not per-serving, unless all upstream fields were ambiguous — document derivation in code comments; tests use linear scaling from stored per-recipe macros.

**Errors:** unknown id → **`404`** JSON envelope.

---

### `POST /mealplan`

**Purpose:** Add or **replace** the plan for a single weekday.

**Auth:** **Required.**

**Request:** `application/x-www-form-urlencoded` (browser form) **or** `multipart/form` — team picks one; templates must match.

| Field | Type | Notes |
|-------|------|-------|
| `day_of_week` | int | `0..6` (Mon–Sun) |
| `recipe_id` | int | Must exist |
| `servings` | int | > 0 |

**Success:** `302` redirect to **`GET /mealplan`** with flash success.

**Errors:**

| Condition | Status |
|------------|--------|
| Anonymous | `302` login |
| Invalid day / servings | `400` or redirect with flash *(pick one; tests allow redirect + flash for HTML-first)* |

**Upsert semantics:** one row per `(user, day)` — posting again **replaces** `recipe_id` + `servings`.

---

### `GET /mealplan`

**Purpose:** Show the current user’s week grid **Mon–Sun**.

**Auth:** **Required.** Anonymous → `302` login.

**Success:** `200` HTML — must expose **seven** day slots (structure, not copy).

---

### `DELETE /mealplan/<day>`

**Purpose:** Clear **one** day’s entry for the current user.

**Auth:** **Required.**

**Path param:** `day` is integer **`0..6`** with the same weekday mapping.

**Success:** `302` → `GET /mealplan` + flash.

**Ownership:** Users only manipulate **their own** rows. Attempting to tamper with another user’s row **by day alone** is meaningless — `day` is scoped to current user. (No cross-user URL.)

**Errors:** if nothing planned that day, **`404`** (or idempotent **302** with “nothing to delete” — pick one in implementation; tests prefer **`404`** for “no plan for that day”.)

---

## 4. Authorization rules

| Resource / action | Who | Notes |
|-------------------|-----|------|
| Search, recipe detail, nutrition JSON | **Public** | Rate limits still apply at Edamam |
| Scale JSON, all meal-plan routes | **Authenticated** | Redirect (`302`) to login if anonymous |
| Meal-plan rows | **Owner only** | Scoped by `user_id = current_user.id` |

**OWASP-style “not yours” rule (Week 6 scope):** routes are only **`/mealplan`** scoped to **session user**. Cross-user attacking is not applicable via IDOR URLs. If you introduce recipe ownership later, use **`404`** for unauthorized rows — never `403` for existence leaks.

**Flask-Login:** Db-and-security implements `login_user`, `logout_user`, `current_user`, `@login_required`. Until merged, skeleton session cookies are acceptable **only** if tests can’t land — target is Flask-Login per assignment Study Guide.

---

## 5. External API contract — Edamam Recipe Search API

**Primary integration:** Edamam **Recipe Search API v2** — documented at Edamam (developers site). **Backup** USDA FoodData Central is **optional** and not exercised in Week 6 tests (Known limitation).

**Request (app server → Edamam):** `GET https://api.edamam.com/api/recipes/v2`

**Query parameters (minimum):**

| Param | Value |
|--------|--------|
| `type` | `public` |
| `q` | Search string from user |
| `app_id` | From env `EDAMAM_APP_ID` |
| `app_key` | From env `EDAMAM_APP_KEY` |

**Timeout:** **4 seconds** socket read timeout on every outbound call implementing search/detail hydration.

**Rate limiting:** Edamam free developer tier — propagate **`429`** as `rate_limited` user messaging on the HTML search page per §3.

**Expected elements in response (for parsing):** hits containing **recipe URI/id**, **label**, **image**, **yield**, **calories/macros** — map into `recipes` + `ingredients` rows. Exact JSON path is implementation **private**; **tests mock HTTP** with a **fixture JSON** committed next to tests **or** inline in tests.

**Failure handling:** Map to the four user-facing codes in §3. Log server-side details (`logger.exception` in `upstream_invalid` / `upstream_error`).

---

## 6. Known limitations (deliberate)

- **Indefinite recipe cache.** Foodie persists Edamam results **without TTL**. Acceptable for **course demo** scope: Edamam’s terms allow **transient caching for performance**; a production deployment would revisit compliance — options: **(a)** Edamam Premium / licensing, **(b)** time-to-live + refresh, **(c)** migrate primary source to **USDA FoodData Central**. Week 6 explicitly chooses **demo-grade indefinite cache** to save quota and complexity.
- **One meal per day.** Multi-slot days (breakfast/lunch/dinner) **deferred**.
- **“Save recipe” language** in the About page means **assign to meal plan**, not a separate favorites table in Week 6.
- **Anonymous search consumes Edamam quota** — acceptable for demo; production would add auth-gated search or server-side caching policies.
- **CSRF:** forms don’t yet use CSRF tokens — acceptable Week 6; Week 7 hardening per course roadmap.
- **Backup USDA API** — not wired in Week 6 automated tests.

---

## 7. Role boundaries

### Server-side — **Sam (TR4UM)**

**Owns:**

- New routes in `app.py` (or `routes.py` if team agrees + coordinator signs off): **`/recipes/search`**, **`/recipes/<id>`**, **`POST /recipes/scale`**, **`GET /nutrition/<id>`**, **`POST /mealplan`**, **`GET /mealplan`**, **`DELETE /mealplan/<day>`**
- `requests` calls to Edamam + timeout + error mapping
- `tests/test_server_edamam_routes.py`

**Does not touch:** templates (Asia), SQLModel security refactor plumbing beyond wiring routes to models (Justin drives LoginManager), unrelated skeleton routes.

---

### Client-side — **Asia (LemonBirdy)**

**Owns:**

- New/updated templates under `templates/` for search, detail, meal-plan week grid, nav updates in `templates/base.html`
- CSS/JS under `static/` as needed
- `tests/test_client_recipe_templates.py`

**Does not touch:** Edamam integration code (Sam), schema models (Justin).

---

### DB-and-security — **Justin (SpartenLife)**

**Owns:**

- SQLModel models for **`recipes`**, **`ingredients`**, **`mealplans`**
- Flask-Login setup + `user_loader`, replacing raw `session["user_id"]` usage per Study Guide
- DB constraints (`UNIQUE`, FKs, `CHECK`) matching §1
- `tests/test_db_schema_and_auth.py`

**Does not touch:** Edamam HTTP wiring, template HTML text/copy (Asia).

---

### Coordinator — **Sowmya Korasikha**

**Owns:**

- `CONTRACTS.md`, `coord_session.md`
- Coordinator-authored tests including **`tests/test_integration.py`**
- Contract revision PRs if requirements change mid-week
- Saturday whole-system e2e narrative in `e2e.md` (with team)

**Does not touch:** teammates’ lanes without team agreement.

---

## 8. Saturday demo script (team walk)

1. Anonymous: `/recipes/search?q=tomato` → results render (or graceful failure banner if quota exceeded — still demonstrate flash).
2. Click through to **`/recipes/<id>`** for a hit.
3. Open **`/nutrition/<id>?servings=4`** in browser (JSON) — shows scaled macros.
4. Register → **`POST /recipes/scale`** via UI (or documented form) for `target_servings`.
5. **`POST /mealplan`** assign recipe to **Tuesday** (`day_of_week=1`).
6. **`GET /mealplan`** shows the slot.
7. **`DELETE /mealplan/1`** clears Tuesday; planner updates.
8. Log out; attempt **`GET /mealplan`** → redirected to login.

All automated tests (`pytest`) green at submission time.
