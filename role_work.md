# role_work.md — Sowmya Korasikha (Coordinator)

**Week:** 7  
**Role:** Coordinator

## Files touched

- `app.py` — `load_dotenv()`, required env vars, nullable `password_hash`, `GET /test/login/<username>` backdoor
- `requirements.txt` — `python-dotenv`, `playwright`, `pytest-playwright`
- `tests/conftest.py` — default env vars for unit tests / CI
- `tests/e2e/conftest.py` — `TESTING=True`, SQLite live-server fixture
- `tests/e2e/test_smoke_login_page.py` — coordinator smoke test
- `templates/login.html` — minimal **Sign in with GitHub** link (stub `href`; Asia restyles, Sam adds route)
- `.github/workflows/test.yml` — CI env vars for required secrets
- `.env.example` — (prior PR) OAuth placeholder names

## Playwright test

**File:** `tests/e2e/test_smoke_login_page.py`  
**Function:** `test_app_starts_login_page_has_clickable_github_button`

**What it verifies:** The app serves `/login` in a real browser, the page title renders, and a **Sign in with GitHub** link is visible, enabled, points at `/login/github`, and accepts a click. This is the cheapest canary that OAuth UI entry exists; it does **not** exercise GitHub or the callback (backdoor / manual gap per `CONTRACTS.md` §11).

**Week 6 walkthrough adapted:** None — new minimal smoke path focused on login-page entry only.

## Known gaps

- EC2 instance disk full — `playwright install chromium` fails locally with ENOSPC; e2e smoke test runs in GitHub Actions CI instead.

- `/login/github` route not implemented yet (Sam) — smoke test only clicks the link, does not assert OAuth completion.
- Navbar still shows `Hi, {username}` until Asia lands **`Logged in as`** copy.
- `oauth_identities` table not created yet (Justin) — backdoor creates `users` rows only.
