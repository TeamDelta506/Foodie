# role_coord.md — Coordination (4-person team)

**Project:** Foodie — Recipe Scaler and Meal Planner  
**Team:** TeamDelta506 (Sam, Asia, Justin, Sowmya)  
**Role:** Coordinator  
**Date:** 2026-06-02

---

## 1. Secrets, in three places

**Example secret:** `OAUTH_CLIENT_SECRET` — the password GitHub gives our OAuth app so Foodie can finish "Sign in with GitHub."

| Place | Where for Foodie |
|-------|------------------|
| **Generated** | GitHub → Settings → Developer settings → OAuth Apps |
| **Stored** | Render dashboard (production), gitignored `.env` (local dev), dummy values in CI (`.github/workflows/test.yml`) |
| **Used at runtime** | `app.py` reads it when a user lands on `/auth/github/callback` and we trade GitHub's code for a login token |

**Fourth place — what goes wrong:** If the secret also shows up in git, Discord, CI logs, or a Docker image, someone else can pretend to be our app during login. That is why we DM credentials in Week 7 and never commit them. `render.yaml` uses `sync: false` so secrets are typed into Render by hand, not pulled from the repo.

The same three-place pattern applies to `SECRET_KEY` and `EDAMAM_APP_KEY`.

---

## 2. Tag-driven releases

**What we do now:** Every push to `master` runs CI (`.github/workflows/test.yml`). Render deploys automatically when `master` updates. We do **not** use git tags to trigger deploys.

**For tag-driven (push a tag like `v1.0.0` to release):**

- **Pro:** You choose exactly which commit goes live. Easy rollback — redeploy an old tag if OAuth breaks after a merge.
- **Con:** Extra step for a small team. We already wait for green CI before merging. Tagging every fix would slow down the merge → test → check Render loop Asia used this week.

**My take:** Tags make sense before Week 9 real hosting. For Week 8, merge to `master` + green CI was enough for us.

---

## 3. When CI goes red

**Scenario:** The GitHub Actions **Tests** job fails.

**First — find the failing step**

- **"Services failed to start"** → nginx or gunicorn did not boot (check Docker logs).
- **During `pytest`** → the stack started, but a test broke.

**Next — use the logs**

CI prints `docker compose -f docker-compose.prod.yml logs` on failure. I look for:

- Missing TLS certs (`cert.pem` / `key.pem`) — CI generates these; if that step was skipped, nginx won't start.
- Python import errors or gunicorn socket errors in the app container.
- Recent changes to `deploy/nginx/nginx.conf`, `gunicorn.conf.py`, or `app.py` — Week 8 merges often break here.

**Reproduce locally:** `docker compose -f docker-compose.prod.yml up --build`, then `pytest -v`.

**Good LLM questions:** Paste the actual error log and ask "why won't curl to https://localhost/ connect?" or "could this pytest failure be from nginx rate limits on `/login`?"

**Bad LLM questions:** "Why did our PR fail?" with no log. "What OAuth secret goes in Render?" — secrets are not in the repo. "Does green CI mean Render is fine?" — CI tests docker-compose with nginx; Render runs gunicorn only. Those are related but not the same.

---

## 4. The composition problem

Everyone's hardening has to live in **one** running stack. Asia's headers, Sam's backend settings, and Justin's nginx filters all end up in the same files — especially `deploy/nginx/nginx.conf`.

**Example we actually hit: CSP vs Bootstrap**

Asia loads Bootstrap from `cdn.jsdelivr.net` in `templates/base.html`. An early nginx CSP of `default-src 'self'` would block that CDN — pages would look broken (no Bootstrap styles/scripts).

The fix in our merged config is to allow jsDelivr in CSP:

```nginx
style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net;
script-src 'self' https://cdn.jsdelivr.net;
```

**Another example: secure cookies**

Justin set `SESSION_COOKIE_SECURE=1` in docker-compose. That only works if Sam's `ProxyFix` in `app.py` sees HTTPS from nginx (`X-Forwarded-Proto: https`). Without it, the browser drops the session cookie and the user looks "logged out after every redirect" — even though Asia's templates are fine.

**How I catch this before merge:** Read the full merged nginx config, not just my slice. Run CI. When a PR touches CSP, I check templates for any external CDN or script source that CSP must allow.

---

## 5. LLM probe

See **`llm_probe_coord.md`** for the deploy-pipeline audit conversation.
