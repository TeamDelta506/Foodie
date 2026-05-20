# Foodie — End-to-End Walk

**Team:** TeamDelta506  
**Coordinator:** Sowmya Korasikha  
**Walked:** May 2026, before Week 6 submission  
**Repo:** https://github.com/TeamDelta506/Foodie (`master`)

Binding spec: [`CONTRACTS.md`](https://github.com/TeamDelta506/Foodie/blob/master/CONTRACTS.md). Per-role slice walks: `e2e/client_side.md`, `e2e/db_security.md`, `e2e/server_side.md`.

---

## 1. Definition

End-to-end for Foodie means a user can move through the full Week 6 product path: discover recipes, open a detail page, scale nutrition, save a recipe to a weekday meal plan, view the planner, clear a day, and hit auth boundaries when logged out — with Flask talking to the real database (and, on a manual walk with keys set, live Edamam).

The system spans four boundaries: **browser ↔ Flask**, **Flask ↔ Postgres/SQLite**, **Flask ↔ Edamam**, and **Flask-Login session**. Role-level `pytest` files mock Edamam and exercise slices; **`tests/test_integration.py`** mocks Edamam once and runs the **whole §8 flow** in one test. This document ties that coordinator integration test, **24/24 `pytest`** on `master`, and the three per-role `e2e/*.md` walks into one team narrative.

---

## 2. The walk

Structured around **`CONTRACTS.md` §8** (Saturday demo script). Each step has a concrete action and expected outcome.

### Setup

**Step 0.** Clone `master`, install deps, run tests.

```bash
git checkout master && git pull origin master
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -v
```

**Expect:** All tests pass (24 at submission). Optional: `docker compose up` and repeat key steps in a browser at `http://localhost:5000` with `EDAMAM_APP_ID` / `EDAMAM_APP_KEY` in `.env` for live search.

### Demo script (§8)

| Step | Do | Expect |
|------|-----|--------|
| **1** | Anonymous: open `/recipes/search?q=tomato` | **200** HTML; results from cache/Edamam, or graceful failure banner (still **200**) per §5 |
| **2** | Click through to `/recipes/<id>` for a hit | **200** detail: title, ingredients, link to nutrition |
| **3** | Open `/nutrition/<id>?servings=4` | **200** JSON; macros scaled for `servings` (§3) |
| **4** | Register; scale via UI or `POST /recipes/scale` with `target_servings` | **200** JSON with scaled `ingredients` (login required) |
| **5** | `POST /mealplan` — assign recipe to **Tuesday** (`day_of_week=1`) | **302** → `/mealplan` |
| **6** | `GET /mealplan` | **200** planner; Tuesday slot shows recipe |
| **7** | `DELETE /mealplan/1` | **302**; Tuesday cleared |
| **8** | Log out; `GET /mealplan` | **302** → login |

Cross-role surfaces exercised: search/detail templates (Asia), routes + Edamam handling (Sam), schema + Flask-Login + meal-plan ownership (Justin), integration boundaries (coordinator).

---

## 3. Pass criteria

| Area | Pass when |
|------|-----------|
| **Automated** | `pytest` → **24 passed**, including `tests/test_integration.py` |
| **Step 1** | **200** HTML; `q` preserved; upstream failures use contract banners, not **500** |
| **Step 2** | Detail uses internal `recipes.id` in URLs (not Edamam URI) |
| **Step 3** | JSON includes `recipe_id`, `servings`, scaled nutrient fields per §3 |
| **Step 4** | Anonymous scale → **302**/**401**; logged-in scale → **200** with `target_servings` |
| **Steps 5–7** | Meal plan **POST**/**GET**/**DELETE** match §3 status codes; one slot per weekday |
| **Step 8** | Anonymous `/mealplan` → **302** login |
| **Repo** | `CONTRACTS.md`, `coord_session.md`, `e2e.md`, tests, no secrets committed |

---

## 4. Execution log

| Step | Result | Notes |
|------|--------|-------|
| **0 (pytest)** | **PASS** | **24/24** on `master` (EC2 `~/Foodie`, May 2026, ~2.9s). Tip: `d0d2558` merge PR #9 (db & security) on current `master`. |
| **1** | **PASS** | `test_recipes_search_*`, integration search step; mocked/live Edamam paths in `e2e/server_side.md` |
| **2** | **PASS** | Integration + `test_recipes_search` HTML links to `/recipes/<id>` |
| **3** | **PASS** | `test_get_nutrition_json_shape` + integration `GET /nutrition/<id>?servings=3` |
| **4** | **PASS** | `test_post_scale_requires_authentication` + integration scale JSON |
| **5** | **PASS** | Integration `POST /mealplan` → **302** |
| **6** | **PASS** | Integration `GET /mealplan` shows `recipe_id` |
| **7** | **PASS** | Integration `DELETE /mealplan/1` → slot cleared |
| **8** | **PASS** | `test_mealplan_get_requires_authenticated_user`; logout flow in `test_auth` |

**Summary:** **9/9 rows pass** for the coordinator-led whole-system check on `master`, driven primarily by **`test_week6_demo_register_search_detail_scale_plan_delete`** plus the role test suites. Per-role browser/SQL walks are documented in `e2e/*.md`.

### Finding — slice e2e vs merged `master` (resolved)

While client templates were ahead of server routes, `e2e/client_side.md` logged **405** on `POST /mealplan` and **404** on `DELETE /mealplan/<day>`. After Sam/Justin server work merged to `master`, **`tests/test_integration.py`** and meal-plan auth tests pass; the UI wiring Asia documented was correct — the gap was missing routes, not templates.

**Lesson:** Per-role walks are valuable mid-week; the coordinator integration test on merged `master` is the authoritative cross-role check before submit.

---

## 5. Per-role contributions

| Role | Teammate | What they contributed |
|------|----------|------------------------|
| **Server-side** | Sam | Edamam search, detail, scale, nutrition JSON, meal-plan routes; `e2e/server_side.md`; `tests/test_server_edamam_routes.py` (5 tests) |
| **Client-side** | Asia (`citronoiseau`) | Templates, Bootstrap, scale `fetch`, meal-plan grid; `e2e/client_side.md`; `tests/test_client_recipe_templates.py` (4 tests) |
| **DB & security** | Justin | SQLModel schema, Flask-Login, meal-plan scoping; `e2e/db_security.md`; `tests/test_db_schema_and_auth.py` (7 tests) |
| **Coordinator** | Sowmya | `CONTRACTS.md`, `coord_session.md`, CI/contracts PR, **`tests/test_integration.py`**, this **`e2e.md`** |

**Coordinator role in this walk:** Composed the §8 table from `CONTRACTS.md`, ran **`pytest`** on merged `master`, and reconciled per-role `e2e/*.md` logs with the green integration test. Sam/Justin/Asia authored slice definitions and execution detail in `e2e/`.

---

## 6. What we'd do differently next time

- Run the **§8 browser walk** once in the middle of the week (not only `pytest`), especially with live Edamam keys, so template vs route gaps surface before merge day.
- Treat **`test_integration.py` green on `master`** as the team “ready for e2e.md” gate, not only each role’s slice tests in isolation.

---

## Appendix — pytest inventory (submission)

```
tests/test_auth.py                          7 passed
tests/test_client_recipe_templates.py       4 passed
tests/test_db_schema_and_auth.py            7 passed
tests/test_integration.py                   1 passed
tests/test_server_edamam_routes.py          5 passed
────────────────────────────────────────────────────
Total                                      24 passed
```
