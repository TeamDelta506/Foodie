# E2E — DB-and-security slice (Justin / schema + Flask-Login)

## Definition

End-to-end for **this slice** means every constraint from CONTRACTS.md §1 is enforced **by Postgres itself** (not just the ORM), and Flask-Login correctly gates protected routes and scopes meal-plan data to the authenticated user.

---

## Walk (do → expect)

1. **Schema inspection** — `docker compose exec db psql -U app -d app`, then run `\d recipes`, `\d ingredients`, `\d mealplans`. **Expect:** column names/types, NOT NULL, FKs, and CHECK constraints match CONTRACTS.md §1 exactly.
2. **UNIQUE(api_id) enforcement** — Insert a recipe, then insert a second row with the same `api_id`. **Expect:** Postgres rejects the second INSERT with a unique-violation error, proving the constraint lives in the DB, not just SQLModel.
3. **UNIQUE(user_id, day_of_week) enforcement** — Insert two `mealplans` rows with the same `user_id` and `day_of_week`. **Expect:** Postgres rejects the duplicate.
4. **CHECK constraints** — Attempt three bad INSERTs: `default_servings = 0` on `recipes`, `quantity = -1` on `ingredients`, `day_of_week = 7` on `mealplans`. **Expect:** All three rejected by CHECK constraints at the DB level.
5. **ON DELETE CASCADE (ingredients)** — Insert a recipe and an ingredient referencing it. DELETE the recipe. **Expect:** The ingredient row is automatically removed.
6. **ON DELETE CASCADE (mealplans via user)** — Insert a user and a mealplan referencing that user. DELETE the user. **Expect:** The mealplan row is automatically removed.
7. **ON DELETE RESTRICT (mealplans via recipe)** — Insert a recipe and a mealplan referencing it. Attempt to DELETE the recipe. **Expect:** Postgres blocks the delete with a foreign-key violation.
8. **Auth flow (browser)** — Register a new user, log in, visit `/mealplan` (expect 200). Log out, visit `/mealplan` (expect 302 → `/login`). Open browser dev tools → Application → Cookies; confirm `session` cookie contains Flask-Login's `_user_id` key (not raw `user_id`).
9. **Ownership probe** — Log in as user A, POST a meal-plan entry. Log in as user B, attempt to GET `/mealplan`. **Expect:** user B sees only their own (empty) plan, not user A's. Meal-plan routes scope queries by `current_user.id`, so cross-user data is never visible (returns 404 or empty, never 403).

---

## Pass criteria (appeared vs actually)

| # | Appeared OK | Actually OK |
|---|-------------|-------------|
| 1 | Tables exist in `\dt` | `\d <table>` shows exact column types, NOT NULL, FK references, CHECK names |
| 2 | ORM raises IntegrityError | Raw `INSERT INTO recipes … VALUES (…)` in psql gets `duplicate key value violates unique constraint` |
| 3 | ORM rejects duplicate | Raw `INSERT INTO mealplans …` in psql gets unique violation |
| 4 | Python raises ValueError | Raw SQL `INSERT` in psql gets `new row … violates check constraint` for each case |
| 5 | Ingredient gone from ORM query | `SELECT * FROM ingredients WHERE recipe_id = …` returns 0 rows in psql |
| 6 | MealPlan gone from ORM query | `SELECT * FROM mealplans WHERE user_id = …` returns 0 rows in psql |
| 7 | App shows error page | psql `DELETE FROM recipes WHERE id = …` returns `update or delete … violates foreign key constraint` |
| 8 | Page loads after login | Session cookie decoded (Flask debug or browser tools) contains `_user_id`, and `/mealplan` returns 302 when logged out |
| 9 | User B sees empty plan | DB query `SELECT * FROM mealplans WHERE user_id = <B>` is empty; user A's row untouched |

---

## Deployment prerequisite

Compose must mount **this** repo (`/home/ubuntu/Foodie/Foodie`), not an older checkout. A stale stack mounted `Foodie-1/Foodie` (no `Recipe` model, raw `session["user_id"]`); Postgres then had only `users` until schema was applied from the branch.

Before browser e2e, from the repo root:

```bash
docker compose down
docker compose up --build -d
docker compose exec app grep -c "class Recipe" /app/app.py   # expect: 1
docker compose exec db psql -U app -d app -c "\dt"           # expect: users, recipes, ingredients, mealplans
```

If tables are missing after `up`, restart the `app` service once so `SQLModel.metadata.create_all(engine)` runs against the new models.

---

## Execution log

**Last verified:** 2026-05-16 (branch `week6/db&security`)

| Step | Result | Notes |
|------|--------|-------|
| 1 | **Pass (Postgres)** | After `create_all` from branch `app.py`: `\d recipes`, `\d ingredients`, `\d mealplans` match CONTRACTS.md §1 — column types, NOT NULL, `ix_recipes_api_id` UNIQUE, `uq_mealplans_user_day`, CHECK names (`ck_recipes_default_servings`, `ck_ingredients_quantity`, `ck_mealplans_day_of_week`, `ck_mealplans_servings`), FKs with `ON DELETE CASCADE` / `RESTRICT`. `recipes.created_at` is `timestamptz`. Skeleton `users.created_at` remains `timestamp without time zone` (Week 5 carry-forward). |
| 2 | **Pass (Postgres)** | Second `INSERT` with same `api_id` → `duplicate key value violates unique constraint "ix_recipes_api_id"`. |
| 3 | **Pass (Postgres)** | Second `INSERT` on same `(user_id, day_of_week)` → `duplicate key value violates unique constraint "uq_mealplans_user_day"`. |
| 4 | **Pass (Postgres)** | All three bad INSERTs rejected: `ck_recipes_default_servings`, `ck_ingredients_quantity`, `ck_mealplans_day_of_week`. |
| 5 | **Pass (Postgres)** | `ingredients` count 1 → 0 after `DELETE FROM recipes` (CASCADE). |
| 6 | **Pass (Postgres)** | `mealplans` count 1 → 0 after `DELETE FROM users` (CASCADE). |
| 7 | **Pass (Postgres)** | `DELETE FROM recipes` while referenced by `mealplans` → FK violation on `mealplans_recipe_id_fkey` (RESTRICT). |
| 8 | **Pass (Flask test client); browser pending** | Register/login stores `_user_id` (not `user_id`); anonymous `GET /mealplan` → 302 → `/login?next=%2Fmealplan`. **Manual:** repeat in browser after Compose serves this branch; confirm cookie in devtools. |
| 9 | **Pass (Flask test client + pytest)** | User A `POST /mealplan` → row in DB. User B `GET /mealplan` → 200, no A recipe in HTML; B has 0 rows in DB. User B `DELETE /mealplan/0` → **404**; A's row unchanged. Covered by `test_mealplan_scoped_to_current_user` and `test_mealplan_delete_missing_day_returns_404`. |

**Pytest (2026-05-16):**

- `tests/test_db_schema_and_auth.py` — **7 passed** (schema, Flask-Login init, auth gate, ownership isolation, DELETE 404)
- `tests/test_auth.py` — **7 passed** (no regressions from Flask-Login refactor)

```bash
python3 -m pytest tests/test_db_schema_and_auth.py tests/test_auth.py -v
```

**Branch code checklist:**

| Item | Status |
|------|--------|
| SQLModel models (`recipes`, `ingredients`, `mealplans`) per CONTRACTS.md §1 | Done |
| Flask-Login (`login_user`, `logout_user`, `current_user`, `@login_required`) | Done; no `session["user_id"]` in root `app.py` |
| `LoginManager` + `@login_manager.user_loader` | Done |
| Meal-plan ownership scoped to `current_user.id` | Done |
| Postgres constraints verified via raw SQL | Done (see steps 1–7) |
| Browser auth cookie walk | **Todo** after `docker compose up` from correct repo path |
