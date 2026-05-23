## Summary

- Adds **Sign in with GitHub** on `/login` and `/register` (password forms kept per CONTRACTS.md §3).
- **Remember me** checkbox (`name="remember"`, value `y`) on both pages; `forms.js` appends `?remember=y` to `/login/github` when checked.
- Navbar copy: **Logged in as {username}** (§9); logout POST unchanged (redirect to `/` is server-side).
- Login/register styling (GitHub primary button, dividers) in `static/css/styles.css`.
- **One Playwright test** — `tests/e2e/test_oauth_navbar.py::test_github_sign_in_shows_username_in_navbar` (Asia Part 2).
- Updated `e2e/client_side.md` (Week 6 walk + OAuth at top, backdoor section, execution log).
- Template pytest in `tests/test_client_recipe_templates.py`; e2e `conftest.py` uses a cross-platform temp DB path.
- `requirements.txt`: `playwright`, `pytest-playwright` for Week 7 e2e.

## Playwright test and dependencies on other roles

The e2e test is **real for client UI** (login page, GitHub click, navbar on `/mealplan`) but uses a **contract-approved stand-in** for GitHub OAuth (§11):

- Playwright **intercepts** `GET /login/github` and returns **302** to `GET /test/login/<username>` (coordinator backdoor).
- It does **not** use `page.goto("/test/login/...")` directly and does **not** drive `github.com`.
- Until **Sam** ships `/login/github` + `/auth/github/callback`, this is the intended automated path.
- **Justin:** CSRF hidden fields not added yet (add when Flask-WTF is enabled); session cookie flags / `oauth_identities` are not required for this test to pass today.
- **Sam:** password login still redirects to `/` in `app.py` (contract wants `/mealplan`); real OAuth can replace the intercept later.

## Client lane status

**Client-side Week 7 scope is complete for now** per CONTRACTS.md §12 (Asia). Follow-ups only when teammates land code (CSRF on forms, optional one-time manual GitHub check per §11 gap).

## Test plan

- [ ] `pytest tests/e2e/test_oauth_navbar.py -v` (run `playwright install chromium` first)
- [ ] `pytest tests/test_client_recipe_templates.py -v`
- [ ] Manual: `/login` and `/register` — layout, Remember me, password forms
- [ ] Manual walk: `e2e/client_side.md` steps 2–13 (meal-plan POST/DELETE remain **Sam**)
