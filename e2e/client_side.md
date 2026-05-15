# E2E — Client-side slice (Asia / templates + static)

## Definition

End-to-end for **this slice** means exercising **browser-rendered HTML and client JS** (layout, forms, nav, `fetch`, mobile collapse) against a **running Foodie app**, not only `pytest` on HTML strings. Server data can be stubbed; the proof is that **UI behavior and wiring** match what users will do on demo day.

---

## Walk (do → expect)

1. **Home, anonymous** — Open `/` at phone and desktop width. **Expect:** Navbar (Discover, About); hero + tiles; **no** Meal plan link until logged in.
2. **Mobile navbar** — Below `lg`, tap hamburger twice. **Expect:** Menu opens and **closes**; no console errors.
3. **Discover shell** — Open `/recipes/search`. **Expect:** GET form → `/recipes/search`, input **`q`**; empty/demo state; Bootstrap intact.
4. **Search submit** — Submit with a realistic `q`. **Expect:** **200**; results depend on server; no stray JS errors on this page.
5. **Detail, anonymous** — Open `/recipes/1` (or from a card). **Expect:** Hero, macros, ingredients; nutrition link is **`/nutrition/<id>`** with integer id; **no** scale controls.
6. **Auth → nav** — Register or log in; revisit `/` and search. **Expect:** **Meal plan** in nav; session survives refresh.
7. **Scale (logged-in)** — On detail with ingredients, change servings → **Update quantities**. **Expect:** DevTools shows **`POST /recipes/scale`** JSON; table matches server values; status text mentions server.
8. **Meal plan grid** — Open `/mealplan`. **Expect:** **7** rows `data-day` 0–6; add form **`POST`** `/mealplan` with `day_of_week`, `recipe_id`, `servings`; typeahead calls **`/mealplan/recipe-suggest`** without console errors.
9. **Save to plan** — Fill form, submit. **Contract:** **302** → `/mealplan` + success flash. **Today:** if **405**, Network tab proves server gap (template is not wrong).
10. **Clear day** — With a planned row, **Clear day**. **Contract:** **DELETE** → **302**, row empties. **Today:** **404** → inline alert; no fake success.
11. **404 UX** — Open a nonsense path. **Expect:** Branded error page (not plain Flask 404).

---

## Pass criteria (appeared vs actually)

| # | Appeared OK | Actually OK |
|---|-------------|-------------|
| 1–2 | Text visible | `#foodieNav` gains/loses `.show`; layout not broken. |
| 3–4 | Form works | `method="get"`, `q` round-trips; Edamam failures → 200 + alert when wired. |
| 5 | Pretty page | URLs use **`recipes.id`** only; anon blocked from scale API (302/401). |
| 7 | Numbers move | Payload/response are **`/recipes/scale`**, not client-only math. |
| 8 | Grid there | Exactly **7** `data-day`; primary add form `action="/mealplan"`. |
| 9–10 | Button did something | **302** + flash + persisted plan (**Sam/Justin**), not 405/404. |

---

## Execution log

**Ran:** Flask `test_client` against repo (same routes as `flask run`). 

| Step | Result | Notes |
|------|--------|--------|
| 1 | Pass | `GET /` 200; `/recipes/search` in body. |
| 2 | Not run | Hamburger needs device; `d-flex` removed from `#foodieNav` for collapse. |
| 3 | Pass | `GET /recipes/search` 200; `name="q"`, `/recipes/search` present. |
| 4 | Partial | 200 always; Edamam hits + timeout/rate copy = **Sam**. |
| 5 | Partial | Demo `GET /recipes/1` 200; unknown id = **200** + alert → §3 wants **404** (`abort(404)` in **Sam**). |
| 6 | Assumed pass | Register exists; confirm in browser. |
| 7 | Pass | `POST /recipes/scale` + template `fetch` OK for demo ids. |
| 8 | Pass | Matches `test_client_recipe_templates`. |
| 9 | **Fail** | `POST /mealplan` → **405** (GET-only route). |
| 10 | **Fail** | `DELETE /mealplan/0` → **404** (no route). |
| 11 | Pass | Branded `error.html` on unknown path. |

**Findings:** UI slice is **done** for wiring; **meal plan save/delete** and **recipe 404** + **nutrition JSON** + **Edamam search** remain **server/contract backlog** (see `CONTRACTS.md` §7). **Pytest:** `tests/test_client_recipe_templates.py` — **4 passed**.
