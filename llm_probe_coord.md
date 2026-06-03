# llm_probe_coord.md — Deploy pipeline security probe

**Project:** Foodie  
**Role:** Coordinator  
**Date:** 2026-06-02

---

## Me

I'm the coordinator on a four-person Flask team (Foodie). Audit our deploy path for:

**(a)** where secrets could leak  
**(b)** what a teammate with repo access could abuse  
**(c)** what's missing for real production  

Here are our key files: `.github/workflows/test.yml`, `render.yaml`, `docker-compose.prod.yml`, `Dockerfile.prod`.

**CI (`test.yml`):** runs on every push/PR to `master`. Sets dummy `SECRET_KEY` and `OAUTH_*` at the job level. Builds `docker-compose.prod.yml`, waits for `https://localhost/`, runs `pytest`.

**Render (`render.yaml`):** deploys `Dockerfile.prod` on push to `master`. Secrets (`OAUTH_*`, `EDAMAM_*`) are `sync: false` — entered manually in the Render dashboard. Live site: `https://foodie-sj2t.onrender.com/`.

**Docker build:** `Dockerfile.prod` runs `COPY . .`. `.dockerignore` excludes `.env` but not `deploy/nginx/certs/`.

---

## LLM

### (a) Secrets leakage

1. **Job-level env in CI.** `test.yml` puts `OAUTH_CLIENT_SECRET` in the job `env:` block. Dummy values today — fine. But if someone swaps in real secrets, every step (including `pip install`) can see them. Real secrets should only be in the one step that needs them.

2. **SECRET_KEY fails open.** In `app.py`, if `SECRET_KEY` is missing, the app falls back to `"dev-secret-not-for-production"` — a string that is in our public repo. A misconfigured deploy could run with a guessable session key and nobody would notice. Production should refuse to start without a real key.

3. **Certs copied into the app image.** CI creates `deploy/nginx/certs/*.pem` before `docker build`. `COPY . .` can bake those into the app image even though only nginx needs them. Fix: add `deploy/nginx/certs/` to `.dockerignore`.

4. **Two deploy paths.** CI tests nginx → gunicorn → postgres. Render runs gunicorn only — no nginx. Secrets and OAuth callback URLs must be set correctly in both places. We saw this when Asia's live site needed the GitHub OAuth callback updated separately from the code.

### (b) Hostile collaborator

1. **Edit the workflow.** Anyone who can push to `master` can add a step to `test.yml` that sends secrets to an outside server. Fix: require PR review on `.github/workflows/` changes.

2. **Flip `ENABLE_TEST_LOGIN=1` on Render.** That turns on `/test-login` — log in as any user with no password. On Render there is no nginx edge filter as a backup.

3. **Merge a weakening change.** Remove `ProxyFix`, turn off secure cookies, or loosen CSP. CI won't catch everything — our Playwright tests use a test-login backdoor, not real GitHub OAuth.

### (c) Missing for real production

- No tag-based releases — Render deploys every `master` push
- No rollback button — revert git and wait for rebuild
- Render has no nginx — Justin's rate limits and edge filters do not run on the live site
- No secret rotation plan for OAuth or Edamam keys
- Some packages in `requirements.txt` use `>=` instead of pinned versions

---

## Me

We're a class team with a demo Saturday. Top three fixes?

## LLM

1. Keep dummy secrets in CI; never put real ones at job scope. Add a startup check that production refuses to boot without a real `SECRET_KEY`.
2. Add `deploy/nginx/certs/` to `.dockerignore`.
3. Document in README that CI/local prod uses the full nginx stack, but Render does not — so the live demo may behave differently from what CI tests.

---

## In my own words

**What surprised me:** I thought going live on Render meant our full nginx → gunicorn stack was deployed. It is not. Render runs gunicorn only. Justin's rate limits and attack-path filters run in CI and local docker — not on `foodie-sj2t.onrender.com`. That is why fixing GitHub OAuth was a GitHub-settings change, not an nginx edit.

**What I'd actually do:** Add certs to `.dockerignore`, make `SECRET_KEY` fail loudly in production, and note in README that Render skips nginx so the team does not over-promise at the demo.

**What I'd watch as coordinator:** PRs that touch `.github/workflows/` or `render.yaml` — same as `CONTRACTS.md`. That is where a teammate could accidentally or intentionally leak secrets.
