# E2E — Client-side slice (Asia / templates + static)

**Week:** 7 (extends Week 6 walk)  
**Binding spec:** [`CONTRACTS.md`](../CONTRACTS.md) §3 login UI, §9 session/navbar, §11 test-login backdoor, §12 Asia lane.

## Definition

End-to-end for **this slice** means exercising **browser-rendered HTML and client JS** (layout, forms, nav, `fetch`, mobile collapse) against a **running Foodie app**, not only `pytest` on HTML strings. Server data can be stubbed; the proof is that **UI behavior and wiring** match what users will do on demo day.

**Week 7 adds:** login/register OAuth entry, **Remember me** markup, navbar **`Logged in as {username}`**, logout POST → home. Automated OAuth completion uses the **test-login backdoor** (§11), not `github.com`.

---

## Prerequisites

```bash
pip install -r requirements.txt
playwright install chromium
```

E2e uses `tests/e2e/conftest.py`: `TESTING=True`, SQLite DB, threaded live server.

```bash
pytest tests/e2e/test_oauth_navbar.py -v
pytest tests/test_client_recipe_templates.py -v
```

---

## The test-login backdoor — code and how to use it

**Route (coordinator / `app.py`, `CONTRACTS.md` §11):** `GET /test/login/<username>` only when `app.config["TESTING"]` is true → `login_user` → **302** `/mealplan`.

**Config wiring (`tests/e2e/conftest.py`):** sets `TESTING=True`, SQLite `DATABASE_URL`, and a `live_server` fixture (`live_server.url`).

**Playwright (Asia — one test, one behavior):** do not `page.goto("/test/login/...")`. Intercept the GitHub start URL, then **click** Sign in with GitHub so the browser follows the backdoor redirect like a real OAuth return.

```python
def test_github_sign_in_shows_username_in_navbar(page: Page, live_server):
    base = live_server.url

    page.route("**/login/github**", lambda route: route.fulfill(
        status=302,
        headers={"Location": f"{base}/test/login/e2e_github_user"},
    ))

    page.goto(f"{base}/login")
    page.get_by_role("link", name="Sign in with GitHub").click()
    # lands on /mealplan

    navbar_user = page.locator(".foodie-nav-user")
    expect(navbar_user).to_be_visible()
    expect(navbar_user.locator(".fw-semibold")).to_have_text("e2e_github_user")
```

**Shipped test:** `tests/e2e/test_oauth_navbar.py` (full assertions per contract navbar copy).

---

## Walk (do → expect)

1. **OAuth sign-in (Week 7)** — Open `/login`; click **Sign in with GitHub**; complete via backdoor (§ above) or manual `/test/login/<user>` when `TESTING=True`. **Expect:** **302** → `/mealplan`; navbar **`Logged in as <username>`**; **Meal plan** in nav.
2. **Home, logged in** — Open `/` at phone and desktop width. **Expect:** Discover, About, **Meal plan**; hero + tiles.
3. **Mobile navbar** — Below `lg`, tap hamburger twice. **Expect:** `#foodieNav` gains/loses `.show`; no console errors.
4. **Discover shell** — Open `/recipes/search`. **Expect:** GET form → `/recipes/search`, input **`q`**; empty/demo state; Bootstrap intact.
5. **Search submit** — Submit with a realistic `q`. **Expect:** **200**; results depend on server; no stray JS errors.
6. **Detail, logged in** — Open `/recipes/1` (or from a card). **Expect:** Hero, macros, ingredients; **`/nutrition/<id>`** with integer id; scale UI when logged in.
7. **Scale (logged-in)** — On detail with ingredients, change servings → **Update quantities**. **Expect:** DevTools **`POST /recipes/scale`** JSON; table matches server.
8. **Meal plan grid** — Open `/mealplan`. **Expect:** **7** rows `data-day` 0–6; add form **`POST`** `/mealplan` with `day_of_week`, `recipe_id`, `servings`; typeahead **`/mealplan/recipe-suggest`** without console errors.
9. **Save to plan** — Fill form, submit. **Contract:** **302** → `/mealplan` + success flash. If **405**, Network tab shows server gap — template wiring still valid.
10. **Clear day** — With a planned row, **Clear day**. **Contract:** **DELETE** → **302**, row empties. If **404**, inline alert — no fake success.
11. **Register OAuth (Week 7)** — Open `/register`. **Expect:** **Sign in with GitHub** at top; password form below divider.
12. **Log out** — Navbar **Log out** POST. **Expect:** **302** → `/`; anonymous nav; `/mealplan` requires login.
13. **404 UX** — Open a nonsense path. **Expect:** Branded `error.html`.

---

## Pass criteria (appeared vs actually)

| # | Appeared OK | Actually OK |
|---|-------------|-------------|
| 1 | GitHub button | `href` `/login/github`; backdoor or intercept; **`Logged in as`** in `.foodie-nav-user` |
| 2–3 | Text visible | Meal plan in nav when authenticated; collapse works |
| 4–5 | Form works | `method="get"`, `q` round-trips |
| 6–7 | Pretty page | `recipes.id` URLs; scale hits **`/recipes/scale`** |
| 8 | Grid there | **7** `data-day`; POST `/mealplan` form fields |
| 9–10 | Button did something | **302** + flash + persistence (**Sam**), not 405/404 |
| 11 | Register GitHub | Same OAuth entry pattern as login |
| 12 | Log out | POST **`/logout`**; meal plan gated |
| 13 | Nice 404 | Branded error template |

---

## Playwright Part 2 (Asia)

**One test function** — `tests/e2e/test_oauth_navbar.py::test_github_sign_in_shows_username_in_navbar` — maps to **walk step 1** (OAuth + navbar). Remaining walk steps: manual browser or `tests/test_client_recipe_templates.py` (HTML structure).

---

## Execution log

**Week 6 run:** Flask `test_client` (historical table in git).

**Week 7 run:** May 2026.

| Step | Result | Notes |
|------|--------|--------|
| 1 (Playwright) | **Pass** | `pytest tests/e2e/test_oauth_navbar.py` |
| 1–11 (manual / pytest HTML) | Mixed | `test_client_recipe_templates` **6 passed**; meal-plan POST/DELETE still **Sam** |
| 12–13 | Partial / pass | Logout UI in `base.html`; branded 404 OK |

**Findings:** Week 7 client templates/static done. One Playwright test per assignment; full walk is manual + template pytest until server routes catch up.
