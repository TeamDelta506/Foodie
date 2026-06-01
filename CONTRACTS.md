# Foodie — CONTRACTS.md

**Team:** TeamDelta506  
**Project:** Foodie — Recipe Scaler & Meal Planner  
**Week:** 7 (extends Week 6 — OAuth, session hardening, Playwright e2e)  
**Coordinator:** Sowmya Korasikha  
**Last updated:** Thursday, May 21, 2026 (PDT) — Week 7 OAuth contract revision

This document is the team’s binding agreement for Week 6 **and Week 7**. Week 6 routes remain in force unless revised below. Routes, tables, JSON envelopes, and failure semantics live here. When code disagrees with this file, **fix the code** unless the team agrees to revise the contract (small follow-up PR: `"Contract revision: <reason>"`).

**Week 7 revision scope (this PR):** GitHub OAuth (`/login/github`, `/auth/github/callback`), `oauth_identities` schema, session hardening (cookie flags, CSRF, lifetime), test-login backdoor, Playwright e2e hooks. Week 6 Edamam/meal-plan contracts unchanged unless noted.

---

## 1. Schema

### Table: `users` (skeleton — carried forward)

Carried from Week 5/6. **Week 7 revision:** `password_hash` may be `NULL` when the account is created exclusively via OAuth (see §9). Password login **must reject** users with `password_hash IS NULL` using the same generic flash as a bad password (no account-type leak).

| Column | Type | Constraints / notes |
|--------|------|------------------------|
| `id` | `INTEGER` | `PRIMARY KEY`, autoincrement |
| `username` | `VARCHAR(80)` | `UNIQUE NOT NULL`, indexed |
| `password_hash` | `VARCHAR(255)` | **nullable** — `NULL` for OAuth-only accounts; non-null Werkzeug hash for password users |
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
### Table: `oauth_identities` (new — Week 7)

Links an external OAuth provider account to a local `users` row. **One local user may have multiple identities** (e.g. GitHub today, Google later) via separate rows sharing the same `user_id`.

| Column | Type | Constraints / notes |
|--------|------|------------------------|
| `id` | `INTEGER` | `PRIMARY KEY`, autoincrement |
| `user_id` | `INTEGER` | `NOT NULL`, `REFERENCES users(id) ON DELETE CASCADE` |
| `provider` | `VARCHAR(32)` | `NOT NULL` — e.g. `'github'` |
| `provider_user_id` | `VARCHAR(64)` | `NOT NULL` — provider stable id (GitHub numeric `id` as string) |
| `provider_login` | `VARCHAR(80)` | nullable — GitHub `login` at link time (audit/display) |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | `NOT NULL`, default now (UTC) |

**Uniqueness:** `UNIQUE (provider, provider_user_id)` — prevents duplicate links to the same GitHub account.

**Indexes:** index on `user_id` for lookup when listing a user’s linked providers.

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

### `GET /login` (existing — Week 7 UI additions)

**Purpose:** Render password login form **and** entry point for OAuth.

**Auth:** Not required.

**Success:** `200` HTML. Page **must** include:

| Element | Requirement |
|---------|-------------|
| Password form | `POST` to `/login` — **kept** (Week 8 may revisit removal) |
| **Sign in with GitHub** | Link or button with `href="{{ url_for('login_github') }}"` or `/login/github` |
| **Remember me** | Checkbox `name="remember"` — value `y` when checked (Asia picks exact markup; Sam/Justin read presence/`y`) |

**Tests:** `tests/e2e/test_smoke_login_page.py` (coordinator); `tests/e2e/test_oauth_navbar.py` (Asia).

---

### `POST /login` (existing — Week 7 redirect alignment)

**Week 7 change:** on successful password auth, **`302` → `/mealplan`** (same deliberate landing as OAuth — replaces Week 6 redirect to `/`).

**Remember me:** pass checkbox into `login_user(user, remember=<bool>)`.

---

### `GET /login/github`

**Purpose:** Start the GitHub OAuth authorization code flow (Authlib `authorize_redirect`).

**Auth:** **Not required** (anonymous initiator).

**Inputs:** none required. Optional query param `next` — internal path only (must start with `/`, no scheme/host); stored in server session and honored after successful callback; default redirect target is **`/mealplan`** if absent or invalid.

**OAuth scope (server → GitHub):** `read:user` (minimum). Do **not** request repo or org scopes for Week 7.

**Remember me (OAuth path):** if the user checked **Remember me** on `GET /login` before clicking GitHub, Sam stores `session["remember_oauth"]=True` when initiating redirect; callback reads it for `login_user(..., remember=...)`, then clears the flag.

**Success:** **`302`** redirect to `https://github.com/login/oauth/authorize` with Authlib-generated `client_id`, `redirect_uri`, `scope`, and `state`.

**Output:** no HTML body — browser leaves Foodie for GitHub.

**Errors:**

| Condition | Status | Behavior |
|-----------|--------|----------|
| Missing OAuth env vars at startup | app fails on import/config | startup crash via `os.environ["KEY"]` |
| Authlib/state setup failure | `302` → `/login` + flash | Log server-side; user-facing flash: *"GitHub sign-in is unavailable. Try again or use password login."* |

**Tests:** Playwright smoke (coordinator) — `tests/e2e/test_smoke_login_page.py` clicks **Sign in with GitHub** link whose `href` resolves here. E2e does **not** follow the real GitHub redirect — see §11.

---

### `GET /auth/github/callback`

**Purpose:** OAuth redirect URI registered with GitHub. Exchange `code` for token, fetch user profile, create-or-link local user, establish Flask-Login session.

**Auth:** **Not required** on entry (anonymous return from GitHub).

**Inputs (query — set by GitHub):**

| Param | Required | Notes |
|--------|----------|-------|
| `code` | Yes on success | Authorization code — single use |
| `state` | Yes | Must match value issued by `/login/github` (Authlib CSRF) |

**Provider profile (GitHub `GET /user`) — fields Foodie requires:**

| GitHub field | Required? | Local use | If missing/null |
|--------------|-----------|-----------|-----------------|
| `id` | **Yes** | `oauth_identities.provider_user_id` (string) | Abort login: flash generic failure, **`302` → `/login`**; log WARNING |
| `login` | **Yes** for new username | `users.username` on create; `provider_login` on link row | Fallback username: `github-{id}` |
| `email` | No | **Not stored** Week 7 | Ignore |
| `avatar_url` | No | **Not stored** Week 7 | Ignore |
| `name` | No | **Not stored** Week 7 | Ignore |

**Create-or-link algorithm (Sam):**

1. Validate `state`; on failure → flash + redirect `/login`.
2. Exchange `code` for token via Authlib. On failure → flash + redirect `/login`; log exception.
3. Fetch GitHub user JSON. If `id` missing → flash + redirect `/login` (never 500 on partial payload).
4. Lookup `oauth_identities` where `provider='github'` AND `provider_user_id=str(id)`.
   - **Found:** load linked `users` row → `login_user(user, remember=remember flag)`.
   - **Not found:** username = `login` or `github-{id}`. If username exists with **no** GitHub identity → **link** (insert identity only). If username free → **create** user (`password_hash=NULL`) + identity. If collision unresolvable → append `-{id}` suffix to username.
5. Clear OAuth scratch keys from Flask `session`.
6. **`302` redirect** to `next` or **`/mealplan`**.

**Token handling:** GitHub access token is used only inside the callback to fetch profile. **Do not persist** access token in DB or session.

**Success response:** **`302`** to `next` or **`/mealplan`**. Response sets session cookie (+ optional `remember_token`). Navbar on landing page shows **`Logged in as {username}`** (§9).

**Errors:** all user-visible OAuth failures → **`302` → `/login`** + flash *"GitHub sign-in failed. Try again or use password login."* (no raw provider error text).

**Tests:** `tests/e2e/test_oauth_login_happy_path.py` (Sam); Part 3 `tests/e2e/test_full_lifecycle.py` first-time + returning login.

---

## 4. Authorization rules

| Resource / action | Who | Notes |
|-------------------|-----|------|
| Search, recipe detail, nutrition JSON | **Public** | Rate limits still apply at Edamam |
| `GET /login`, `GET /login/github`, `GET /auth/github/callback` | **Public** | OAuth initiator + callback |
| Scale JSON, all meal-plan routes | **Authenticated** | Redirect (`302`) to login if anonymous |
| Meal-plan rows | **Owner only** | Scoped by `user_id = current_user.id` |
| `GET /test/login/<username>` | **TESTING only** | 404 when `TESTING` false — §11 |

**OWASP-style “not yours” rule (Week 6 scope):** routes are only **`/mealplan`** scoped to **session user**. Cross-user attacking is not applicable via IDOR URLs. If you introduce recipe ownership later, use **`404`** for unauthorized rows — never `403` for existence leaks.

**Flask-Login (Week 6 — done):** `login_user`, `logout_user`, `current_user`, `@login_required`.

**OAuth (Week 7):** GitHub routes in §3 supplement password login; both coexist. Password form stays on `/login` until a future week retires it.

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
- **CSRF (Week 7):** Flask-WTF CSRF on **every state-changing HTML form**. See §10.
- **Backup USDA API** — not wired in Week 6 automated tests.

---

## 7. Role boundaries (Week 6 baseline — see §12 for Week 7)

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

## 8. Demo scripts

### Week 6 walk (complete)


1. Anonymous: `/recipes/search?q=tomato` → results render (or graceful failure banner if quota exceeded — still demonstrate flash).
2. Click through to **`/recipes/<id>`** for a hit.
3. Open **`/nutrition/<id>?servings=4`** in browser (JSON) — shows scaled macros.
4. Register → **`POST /recipes/scale`** via UI (or documented form) for `target_servings`.
5. **`POST /mealplan`** assign recipe to **Tuesday** (`day_of_week=1`).
6. **`GET /mealplan`** shows the slot.
7. **`DELETE /mealplan/1`** clears Tuesday; planner updates.
8. Log out; attempt **`GET /mealplan`** → redirected to login.

All automated tests (`pytest`) green at submission time.

### Week 7 walk (team Part 3)

1. `/login` — password form + **Sign in with GitHub**.
2. GitHub OAuth (manual once) → **`/mealplan`** + **`Logged in as {username}`**.
3. Row in **`oauth_identities`** for GitHub id.
4. Logout → `/`; `/mealplan` requires login again.
5. Second GitHub login reuses same user/identity row.
6. `pytest tests/e2e/` green including `test_full_lifecycle.py`.


## 9. OAuth session, logout, and first-time user shape

### Local records after first-time GitHub login (same DB transaction)

**`users` row:**

| Column | Type / value |
|--------|----------------|
| `id` | `INTEGER` PK (new) |
| `username` | `VARCHAR(80)` — GitHub `login`, or `github-{id}` fallback, or `{login}-{id}` collision suffix |
| `password_hash` | **`NULL`** |
| `created_at` | `TIMESTAMP WITH TIME ZONE` UTC now |

**`oauth_identities` row (inserted with user):**

| Column | Type / value |
|--------|----------------|
| `id` | `INTEGER` PK (new) |
| `user_id` | `INTEGER` FK → `users.id` |
| `provider` | `'github'` |
| `provider_user_id` | `VARCHAR(64)` — `str(github.id)` |
| `provider_login` | `VARCHAR(80)` — GitHub `login` or `NULL` if absent |
| `created_at` | UTC now |

**Returning GitHub login:** step 4 finds existing identity → **no new rows**; same `users.id` reused.

### Session state immediately after successful callback

**Flask `session` dict immediately before redirect (Flask-Login):**

| Key | Type | Value after successful callback |
|-----|------|----------------------------------|
| `_user_id` | `str` | `str(users.id)` — authenticated user |
| `_fresh` | `bool` | `True` |
| `_id` | `str` | Flask session id (signed) |

**Must be cleared before redirect:** `_oauth_state`, `next`, `remember_oauth`, any Authlib scratch keys.

**Not stored in session after callback:** GitHub access token, GitHub `code`.

**Cookies set on success:**

| Cookie | When | Flags (§10) |
|--------|------|---------------|
| Flask `session` | always | `HttpOnly`, `SameSite=Lax`, `Secure` off in docker dev |
| `remember_token` | Remember me checked | `HttpOnly`, `SameSite=Lax` |

**Navbar (Asia):** visible text **`Logged in as {username}`** (replaces Week 6 `Hi, {username}`).

### Logout — `POST /logout` (existing route — Week 7 semantics unchanged)

**Clears locally (Foodie only):**

| Item | Action |
|------|--------|
| Flask-Login session | `logout_user()` — removes `_user_id`, `_fresh` |
| Signed session cookie | cleared / expired |
| `remember_token` cookie | cleared if present |
| Server-side session data | Flask session emptied |

**Does *not* clear at provider (explicit):**

| Item | Action |
|------|--------|
| GitHub OAuth token | **not** revoked (Foodie does not call GitHub revoke API) |
| GitHub browser session | **unchanged** — user may still be logged in at github.com |
| `oauth_identities` rows | **retained** — logout is session-only, not account deletion |

**Response:** **`302` → `/`** with flash *"You have been logged out."*

**Tests:** `tests/e2e/test_protected_page_auth.py` (Justin); Part 3 lifecycle logout step.

---

## 10. Session hardening and CSRF (Week 7)

**Environment (`python-dotenv` — add to `requirements.txt`):** `load_dotenv()` as **first import side-effect** in `app.py`, before any `os.environ[...]`. Required keys (square-bracket access — crash if missing):

| Variable | Purpose |
|----------|---------|
| `SECRET_KEY` | Signs Flask session cookie |
| `OAUTH_CLIENT_ID` | GitHub OAuth app |
| `OAUTH_CLIENT_SECRET` | GitHub OAuth app |
| `DATABASE_URL` | Postgres (dev) / SQLite (e2e fixture) |

Document names in **`.env.example`** (committed); real values in gitignored **`.env`** only.

**Cookie flags:**

| Setting | Value |
|---------|--------|
| `SESSION_COOKIE_HTTPONLY` | `True` |
| `SESSION_COOKIE_SAMESITE` | `'Lax'` |
| `SESSION_COOKIE_SECURE` | `False` in docker dev; `True` over HTTPS in production |

**Session lifetime:**

| Mode | Duration |
|------|----------|
| Default | **`7 days`** (`PERMANENT_SESSION_LIFETIME`) |
| Remember me | **`30 days`** via `login_user(..., remember=True)` |

**Remember me:** checkbox on `/login` named **`remember`**. Asia wires UI; Sam passes flag on password and OAuth login; Justin configures Flask-Login.

**CSRF:** Flask-WTF on all **`POST`** HTML forms — `/login`, `/register`, `/logout`, `/mealplan`, planner forms. Invalid/missing token → **`400`**.

---

## 11. Test-only routes and external dependency honesty

### `GET /test/login/<username>` (TESTING only)

**Guard:** `if not app.config.get("TESTING"): abort(404)`.

1. Lookup `users.username == <username>`; if missing create `User(username=..., password_hash=NULL)`.
2. `login_user(user)`.
3. **`302` → `/mealplan`**.

Playwright stands in for post-GitHub-redirect login. Does not create `oauth_identities` unless callback is exercised separately.

**Fixture:** `tests/e2e/conftest.py` sets `TESTING=True` and SQLite `DATABASE_URL`.

### `external_dependency: github.com`

**What this contract specifies:** Foodie server behavior — our routes, Authlib exchange, field mapping, DB writes, session cookies, redirects — **given** a successful authorization `code` and a profile JSON shaped like the representative payload below.

**What this contract cannot specify:** GitHub's authorize-page UI, whether the user approves, network failures on github.com, token-endpoint error bodies, rate limits, or field order. Those are verified manually once or left as documented gaps.

**Representative GitHub user profile (Study Guide shape):**

```json
{
  "login": "octocat",
  "id": 583231,
  "avatar_url": "https://avatars.githubusercontent.com/u/583231?v=4",
  "email": null
}
```

**Gap:** Playwright does not drive real `github.com` authorize. Manual verify once; document in `team_walkthrough.md`.

**OAuth app:** dev app under coordinator account; callback `http://localhost:5000/auth/github/callback`; secrets in `.env` only.

---

## 12. Week 7 role boundaries (additions)

### Server-side — **Sam (TR4UM)** — Week 7

- Register Authlib GitHub OAuth client (`OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`)
- Implement **`GET /login/github`**, **`GET /auth/github/callback`** per §3
- Create-or-link algorithm; map missing provider fields per §3 table; **never 500** on partial payload
- Do not persist GitHub access tokens
- **`tests/e2e/test_oauth_login_happy_path.py`** — backdoor or callback mock; assert **`Logged in as <username>`** visible

### Client-side — **Asia (LemonBirdy / citronoiseau)** — Week 7

- **`templates/login.html`:** **Sign in with GitHub** button + existing password form
- Deliberate post-login landing aligns with **`/mealplan`** (navbar visible on protected page)
- **Remember me** checkbox `name="remember"`; logout button clears session → **`/`**
- **`templates/base.html`:** navbar copy **`Logged in as {username}`**
- **`tests/e2e/test_oauth_navbar.py`** — logged-out user clicks GitHub entry → backdoor login → username in navbar

### DB-and-security — **Justin (SpartenLife)** — Week 7

- SQLModel **`OAuthIdentity`** / **`oauth_identities`** table §1; migration or clean schema update
- Nullable **`users.password_hash`**; reject password login when NULL
- Cookie flags §10; `PERMANENT_SESSION_LIFETIME`; remember-me duration
- Flask-WTF CSRF on every state-changing form §10
- Extend **`tests/test_db_schema_and_auth.py`** — assert `oauth_identities` columns + uniqueness
- **`tests/e2e/test_protected_page_auth.py`** — `/mealplan` gated before login, open after backdoor, closed after logout (DOM)

### Coordinator — **Sowmya Korasikha** — Week 7

- **`CONTRACTS.md`**, **`coord_session.md`**, integration log
- **`GET /test/login/<username>`** §11; **`.env.example`**; GitHub OAuth app (dev credentials)
- **`tests/e2e/conftest.py`** — `TESTING=True`, live server, SQLite DB
- **`tests/e2e/test_smoke_login_page.py`** — app starts, login page loads, GitHub button present and clickable

---

## 13. Contract tests map (Week 7)

| Contract clause | Enforcing test(s) |
|-----------------|-------------------|
| §3 `/login/github`, `/auth/github/callback` | Sam e2e; coordinator smoke (button → route) |
| §3 provider field defaults | Sam unit/integration (optional); lifecycle test DB assert |
| §9 first-time user + identity row | Part 3 `test_full_lifecycle.py` first-time login |
| §9 returning login reuses row | Part 3 lifecycle returning login |
| §9 session cookies after callback | Justin e2e protected-page test |
| §9 logout local vs provider | Justin e2e; Part 3 lifecycle |
| §10 CSRF rejection | Part 3 lifecycle tokenless POST |
| §10 session expiry | Part 3 lifecycle short `PERMANENT_SESSION_LIFETIME` |
| §11 test-login backdoor | All role Playwright tests |
| §11 `external_dependency` gap | `team_walkthrough.md` gaps section (Part 3) |

---

Tag submission commit **`week7-final`**.
