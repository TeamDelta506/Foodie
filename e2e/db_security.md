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

## Execution log

| Step | Result | Notes |
|------|--------|-------|
| 1 | **Not run in Postgres yet** | SQLite schema inspection in pytest passes; still need `docker compose exec db psql -U app -d app` to verify real Postgres types and constraints. |
| 2 | **Not run in Postgres yet** | Model defines `UNIQUE` on `recipes.api_id`; raw duplicate INSERT still needs psql verification. |
| 3 | **Not run in Postgres yet** | Model defines `UNIQUE(user_id, day_of_week)`; raw duplicate INSERT still needs psql verification. |
| 4 | **Not run in Postgres yet** | Model defines CHECK constraints for servings, quantity, and day bounds; raw failing INSERTs still need psql verification. |
| 5 | **Not run in Postgres yet** | Model defines `ingredients.recipe_id` with `ON DELETE CASCADE`; psql delete/select verification still needed. |
| 6 | **Not run in Postgres yet** | Model defines `mealplans.user_id` with `ON DELETE CASCADE`; psql delete/select verification still needed. |
| 7 | **Not run in Postgres yet** | Model defines `mealplans.recipe_id` with `ON DELETE RESTRICT`; psql delete verification still needed. |
| 8 | **Pass in Flask test client** | Register/login/logout flow uses Flask-Login and stores `_user_id`; browser cookie inspection still needs manual verification. |
| 9 | **Blocked** | `POST /mealplan` and `DELETE /mealplan/<day>` are still server-route work, so full ownership probing waits on those routes. |

**Pytest:** `tests/test_db_schema_and_auth.py` — **5 passed**. `tests/test_auth.py` — **7 passed** (no regressions from Flask-Login refactor).
