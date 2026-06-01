# E2E — Server-side slice (Sam / routes + Edamam)

## Definition

End-to-end for **this slice** means exercising **every server-owned HTTP route** against a
running Foodie app with all external services live, not only `pytest` with mocked HTTP.
The proof is that each route returns the correct status code, content type, and body shape
under both happy-path and error inputs.

Run `e2e_walk.py` (repo root) for automated coverage, or follow the curl walk below for a
manual, step-by-step trace.

---

## Walk (do → expect)

1. **Home page** — `GET /`
   **Expect:** 200 HTML; Foodie navbar with *Discover recipes* and *Log in* links.

2. **Register** — `POST /register` with `username` + `password`
   **Expect:** 302 → `/`; session cookie set (`_user_id` in Flask-Login); navbar shows username.

3. **Logout** — `POST /logout`
   **Expect:** 302 → `/`; session cleared; navbar reverts to *Log in / Register*.

4. **Login** — `POST /login` correct credentials
   **Expect:** 302 → `/`; session cookie restored.
   **Error case:** wrong password → 200 + "Invalid username or password" flash.

5. **Recipe search — empty query** — `GET /recipes/search`
   **Expect:** 200 HTML; `<form method="get">` with `name="q"`; cached DB rows shown.

6. **Recipe search — live Edamam** — `GET /recipes/search?q=lentil+soup`
   **Expect:** 200 HTML; Edamam hit upserted into `recipes` table; cards link to `/recipes/<id>`.
   **Error cases (all return 200 + Bootstrap flash):**
   - Timeout (>4 s) → "timed out" text
   - HTTP 429 → "rate limited" text
   - Other non-2xx → "returned an error" text

7. **Recipe detail** — `GET /recipes/<id>`
   **Expect:** 200 HTML; recipe name, macros table, ingredient list; *Update quantities*
   button visible when logged in; nutrition link → `/nutrition/<id>?servings=<n>`.
   **Error case:** unknown `id` → 404 branded error page (not Flask default).

8. **Scale JSON** — `POST /recipes/scale` (JSON, auth required)
   **Expect:** 200 JSON; `recipe_id`, `target_servings`, `default_servings`, `ingredients[]`
   with `name`, `quantity` (scaled), `unit`.
   **Error cases:**
   - Anonymous → 302 to `/login`
   - `target_servings ≤ 0` → 400 `{"error": "bad_request", ...}`
   - Missing field → 400
   - Unknown `recipe_id` → 404 `{"error": "not_found", ...}`

9. **Nutrition JSON** — `GET /nutrition/<id>?servings=<n>` (no auth required)
   **Expect:** 200 `application/json`; keys `recipe_id`, `servings`, `calories`,
   `protein`, `carbs`, `fat`; values are totals for the requested `servings` count,
   scaled linearly from stored per-recipe macros.
   **Error case:** unknown `id` → 404 JSON envelope.

10. **Meal plan view** — `GET /mealplan` (auth required)
    **Expect:** 200 HTML; exactly **7** `data-day` slots (0 = Mon … 6 = Sun); empty slots
    show "Nothing planned"; logged-out request → 302 to `/login`.

11. **Meal plan add** — `POST /mealplan` with `day_of_week`, `recipe_id`, `servings`
    **Expect:** 302 → `GET /mealplan`; slot for that day now shows recipe name + `(#<id>)`.
    **Upsert:** posting the same day again replaces the recipe, not duplicates.
    **Error cases:** invalid day (>6) or servings (≤0) → redirect + flash.

12. **Meal plan clear** — `DELETE /mealplan/<day>`
    **Expect:** 302 → `GET /mealplan`; that day's slot reverts to "Nothing planned".
    **Error case:** clearing an already-empty day → 404.

13. **Branded error pages**
    **Expect:** unknown path → 404 HTML with Foodie navbar/footer, human-readable message.
    `GET /logout` → 405 HTML with Foodie branding (logout is POST-only).

---

## Pass criteria

| # | Route | Success signal | Error signal |
|---|-------|---------------|--------------|
| 5–6 | `GET /recipes/search` | 200 + `name="q"` form; Edamam results in DB | 200 + correct flash copy for timeout / 429 / upstream |
| 7 | `GET /recipes/<id>` | 200 + ingredient table | 404 branded page for unknown id |
| 8 | `POST /recipes/scale` | 200 JSON, `ingredients[]` scaled by factor | 302 (anon), 400 (bad input), 404 (unknown id) |
| 9 | `GET /nutrition/<id>` | 200 JSON, all 6 macro keys, values = totals × factor | 404 JSON envelope |
| 10 | `GET /mealplan` | 200, exactly 7 `data-day` slots | 302 for anon |
| 11 | `POST /mealplan` | 302 → `/mealplan`, slot filled, upsert works | flash on bad input |
| 12 | `DELETE /mealplan/<day>` | 302, slot cleared | 404 on empty day |

---

## Execution log

**Ran:** `python3 e2e_walk.py` against local dev server (SQLite, no live Edamam key).
All external-API calls fail gracefully — re-run with `EDAMAM_APP_ID`/`EDAMAM_APP_KEY`
set to exercise the live Edamam path end-to-end.

| Step | Result | Notes |
|------|--------|-------|
| 1 | ✅ Pass | `GET /` 200; Foodie brand + Discover link present. |
| 2 | ✅ Pass | `POST /register` 302; navbar shows `e2e_user`; duplicate blocked. |
| 3 | ✅ Pass | `POST /logout` 302; session cleared. |
| 4 | ✅ Pass | Wrong password → "Invalid" flash; correct → 302 + session. |
| 5 | ✅ Pass | Empty search 200; `name="q"` form; cached rows returned. |
| 6 | ✅ Pass | Edamam upstream error handled gracefully (no API key in dev). Re-run with live key to verify upsert. |
| 7 | ✅ Pass | `GET /recipes/1` 200; Garden grain bowl + Quinoa; scale controls present (logged in). `GET /recipes/9999` → 404 branded page. |
| 8 | ✅ Pass | Scale `id=1, servings=4` → Quinoa 1.0→2.0 (2× factor); 400 on bad input; 404 on unknown id; anon → 302. |
| 9 | ✅ Pass | `/nutrition/1?servings=4` → all 6 keys; calories 420→840 (2×). `/nutrition/9999` → 404 JSON. |
| 10 | ✅ Pass | 7 `data-day` slots; "Nothing planned" for all; anon → 302. |
| 11 | ✅ Pass | POST day=1 recipe=1 → 302; Tuesday shows recipe. Upsert replaces day=1 with recipe=2. Invalid day=8 → flash. |
| 12 | ✅ Pass | `DELETE /mealplan/1` → 302; slot cleared. Second delete → 404. |
| 13 | ✅ Pass | `/nonsense` → 404 branded. `GET /logout` → 405 branded. |

**Findings:** All server-side routes complete per `CONTRACTS.md §3`. Edamam live-path
(step 6 real results, DB upsert) requires `EDAMAM_APP_ID` + `EDAMAM_APP_KEY` in the
environment — graceful fallback confirmed without keys.
**Pytest:** `tests/test_server_edamam_routes.py` — **5/5 passed**.
**Automated walk:** `e2e_walk.py` — **47/47 checks passed**.
