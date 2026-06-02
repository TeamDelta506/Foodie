# Coordinator–LLM Session — Foodie (Week 7 OAuth)

**Project:** Foodie — Recipe Scaler and Meal Planner  
**Team:** TeamDelta506 (Sam, Asia, Justin, Sowmya)  
**Coordinator:** Sowmya Korasikha  
**LLM:** Claude via Cursor IDE  
**Session date:** Thursday, May 21, 2026 (PDT)  
**Working repo:** `github.com/TeamDelta506/Foodie` — branch `week7/contracts-oauth`

---

## Prologue — context before decisions

The LLM reviewed:

1. **Week 6 `CONTRACTS.md` and `coord_session.md`** on `master` — binding spec for Edamam routes, meal plan, Flask-Login password auth.
2. **Live app on EC2** — `User(username, password_hash NOT NULL)`, navbar `Hi, {username}`, post-login redirect to **`/`** (home), logout → home. **24/24 pytest green** on Week 6 tests.
3. **Week 7 assignment** — OAuth via Authlib, Playwright e2e, session hardening, six contract items including honest `external_dependency: github.com`.
4. **OAuth app setup (same day)** — org URL 404’d (Sowmya is org **member**, not owner). Dev OAuth app created under **personal** GitHub account; callback `http://localhost:5000/auth/github/callback`; credentials in gitignored `.env` on EC2; `.env.example` updated with placeholders.

---

## How we ran this session

Same pattern as Week 6: one design fork at a time, coordinator chooses or defaults after noting who is affected. Week 7 adds **cross-role coupling** (Sam’s callback redirect = Asia’s post-login UX = Justin’s session cookies = Playwright assertions).

---

## Session log

### Decision 1 — Post-login landing page (OAuth + password)

**LLM framing:** Week 6 password login redirects to **`/`** (home). OAuth could land anywhere. Protected page makes auth e2e meaningful.

**Options:** **A)** `/` home · **B)** `/mealplan` · **C)** honor `?next=` only

**Coordinator response:** **B — `/mealplan` for both OAuth and password login** (Week 7 alignment). Meal plan is Foodie’s main authenticated surface; Justin’s e2e and Part 3 lifecycle already gate `/mealplan`. Optional internal `?next=` on OAuth start; default **`/mealplan`**.

**Cross-role:** Asia — same landing for both login paths. Sam — callback + `POST /login` redirect. Justin — session cookie before redirect.

---

### Decision 2 — GitHub profile fields and missing-data defaults

**LLM framing:** GitHub may omit `email`; `login` is usually present. Contract must never 500 on partial JSON.

**Coordinator response:**

| Field | Required | Missing behavior |
|-------|----------|------------------|
| `id` | **Yes** | Fail login gracefully → `/login` + flash |
| `login` | Preferred | Fallback username `github-{id}` |
| `email`, `avatar_url`, `name` | No | Ignore — not stored Week 7 |

**Cross-role:** Sam implements mapping. Justin stores only `oauth_identities` + existing `users` columns (no new profile columns). Asia display uses `users.username` only.

**Pushback noted:** Study guide shows email — we deliberately **don’t persist email** Week 7 to avoid schema creep; can revise later if product needs it.

---

### Decision 3 — Link model: one user, multiple OAuth identities

**LLM framing:** Password user later clicks “Sign in with GitHub” — same person, two auth methods.

**Coordinator response:** New **`oauth_identities`** table with **`UNIQUE (provider, provider_user_id)`**. Link algorithm:

1. Known GitHub id → existing identity → login that user  
2. Unknown GitHub id + matching local username without GitHub row → **link**  
3. Unknown GitHub id + no user → **create** OAuth-only user (`password_hash NULL`)

**Cross-role:** Justin owns table + migration + nullable `password_hash`. Sam owns algorithm. Justin’s schema test must assert table exists before Sam’s callback test passes.

---

### Decision 4 — Session state and navbar copy

**LLM framing:** Assignment Playwright examples assert **`Logged in as {username}`**; Foodie currently shows **`Hi, {username}`**.

**Coordinator response:** Contract requires navbar **`Logged in as {username}`** for Week 7 e2e consistency. Asia updates `base.html`.

**Session after callback:** Flask-Login `_user_id` + `_fresh`; `remember_token` when Remember me set. Justin sets cookie flags §10.

---

### Decision 5 — Logout scope

**LLM framing:** Users may expect “log out everywhere.” OAuth providers are separate sessions.

**Coordinator response:** **Local only** — `logout_user()`, clear session + remember cookies. **Do not** revoke GitHub token or log out of github.com. Redirect **`/`** with optional flash.

**Cross-role:** Asia — logout button stays POST form (CSRF token added by Justin). Justin — CSRF on logout form.

---

### Decision 6 — What we cannot put in the contract (external dependency)

**Coordinator response:** Document **`external_dependency: github.com`** in §11 with representative JSON only. Playwright uses **`/test/login/<username>`** backdoor — does not replace manual one-time GitHub redirect check. Gap named for `team_walkthrough.md`.

**Cross-role:** Coordinator owns backdoor + `tests/e2e/conftest.py`. All role Playwright tests depend on backdoor until Sam ships real callback (optional mock callback tests).

---

### Decision 7 — Remember me and session lifetime

**Coordinator response:** Default session **7 days**; Remember me **30 days** via Flask-Login `remember=True`. Checkbox name **`remember`** on login form.

**Cross-role:** Asia adds checkbox; Sam passes flag on password + OAuth login; Justin configures `PERMANENT_SESSION_LIFETIME` and cookie flags.

---

### Decision 8 — CSRF (Week 6 limitation closed)

**Coordinator response:** Flask-WTF CSRF on **all state-changing HTML forms** — closes Week 6 §6 limitation. Part 3 lifecycle test will POST without token and expect rejection.

**Cross-role:** Justin enables globally; Asia adds `{{ csrf_token() }}` to every form she owns or touches; Sam ensures any new OAuth-related POST forms include token if added.

---

## Teammate consultation

| Topic | Where | Outcome |
|-------|--------|---------|
| Org OAuth app | GitHub UI | 404 — Sowmya not org owner; **personal dev app** used instead |
| Post-login page | Coordinator default | **`/mealplan`** — will confirm in Discord if Asia/Sam prefer `/` |
| Navbar copy change | Coordinator default | **`Logged in as`** — aligns with assignment e2e wording |

*Note:* Discord ping planned after contract PR opens — teammates can comment on PR before implementing.

---

## Artifacts from this session

| File | Status |
|------|--------|
| `CONTRACTS.md` | Week 7 OAuth sections §3 routes, §9–§12, schema + demo updates |
| `coord_session.md` | This file |
| `.env.example` | OAuth placeholders (prior step, same branch) |

**Not in this PR (coordinator Step 2):** test-login backdoor, `tests/e2e/conftest.py`, Playwright smoke test — follow after team acknowledges contract.

---

## Integration log (Week 7)

| Date | Event | Resolution |
|------|--------|------------|
| 2026-05-21 | Org OAuth settings 404 for coordinator | Personal GitHub OAuth app; documented in §11 |
| — | *(add rows as PRs land)* | |

---

## Reflection

Week 7 contract is harder than Week 6 because **half the behavior lives on GitHub’s servers**. The honest move is naming that gap and giving the team a **test-login backdoor** plus concrete shapes for everything *we* control (DB link table, session cookies, redirect targets). The highest-risk integration point is **create-or-link** when a password user first attaches GitHub — Sam and Justin should pair on that branch before Asia polishes navbar copy.
