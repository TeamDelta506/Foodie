# Study Guide answers — Foodie production stack

Beginner-friendly notes for Week 8 topics. Based on our repo: `docker-compose.prod.yml`, `deploy/nginx/nginx.conf`, `gunicorn.conf.py`, and tests run on **2026-06-01**.

---

## nginx as a request filter (bots, `/wp-login.php`, `/.env`, etc.)

### Why is it better for nginx to 404 these than Flask?

**When nginx answers first**, the junk request never wakes up Python:

| If nginx handles it | If Flask handles it |
|---------------------|---------------------|
| No gunicorn worker used | A worker runs your app code for every scan |
| No Flask session/CSRF/template work | Error handlers and templates still cost CPU |
| Cheaper at high volume | Thousands of bot hits can pile up on 3 workers |
| Clear separation: edge vs app | App logs fill with noise; harder to spot real users |

**Simple analogy:** nginx is a receptionist who turns away cold callers at the door. Flask is the specialist upstairs — you do not want the specialist interrupted 10,000 times a day for wrong-number calls.

### Important detail about *our* config

In `deploy/nginx/nginx.conf` we have a **catch-all**:

```nginx
location / {
    proxy_pass http://foodie_app;
    ...
}
```

That means paths like `/wp-login.php` **are still forwarded to gunicorn**. nginx does not 404 them by itself — Flask’s 404 handler returns the branded “page not found” page.

So today we get the **right HTTP status (404)** for outsiders, but **not** the ideal “Flask never saw it” behavior. To 404 at nginx only, you would add explicit `location` blocks (or a `map`) that `return 404` for known-bad paths **before** the catch-all, or stop using a single `location /` for everything.

### What do Flask / gunicorn access logs look like before and after?

**Before (dev: `docker compose up`, Flask on port 5000)**

Example line you would see in the terminal for every bot probe:

```text
127.0.0.1 - - [01/Jun/2026 12:00:01] "GET /wp-login.php HTTP/1.1" 404 -
127.0.0.1 - - [01/Jun/2026 12:00:02] "GET /.env HTTP/1.1" 404 -
127.0.0.1 - - [01/Jun/2026 12:00:03] "GET /admin/ HTTP/1.1" 404 -
```

Every scan hits the **Flask dev server** directly. No TLS termination at the edge, no nginx static offload, no nginx rate limits.

**After (prod: `docker compose -f docker-compose.prod.yml up`)**

gunicorn still logs proxied junk (because of `location /`), for example:

```text
172.19.0.1 - - [01/Jun/2026:20:30:32 +0000] "GET /wp-login.php HTTP/1.0" 404 5484 "-" "curl/8.5.0"
```

**What changed anyway:**

- **nginx access log** (separate from gunicorn) records the same hits at the edge.
- **`/static/`** is served by nginx — those requests **do not** appear in gunicorn logs.
- **TLS** happens in nginx; gunicorn only sees HTTP on the unix socket.
- **`/login`** (and OAuth paths) can be **rate-limited** at nginx before Python runs.

**If `SECRET_KEY` is missing** (misconfigured deploy), unknown paths can return **500** instead of 404 because Flask cannot use sessions — we saw that in testing. Always set `SECRET_KEY` in `.env` for production.

---

## Script-kiddie attack-path test (Study Guide §10)

### What we did

1. Copied `attack_paths.json` (20 known-bad URLs) and `tests/test_attack_paths.py` into the repo.
2. Ran the prod stack: `docker compose -f docker-compose.prod.yml up -d` with `SECRET_KEY` set.
3. Ran: `pytest tests/test_attack_paths.py -v`

### Results

| Run | Result | Notes |
|-----|--------|-------|
| Without `SECRET_KEY` | **20 failed** | Every path returned **HTTP 500** (session error in Flask). |
| With `SECRET_KEY` set | **20 passed** | Every path returned **404** (Flask 404 page). |
| `test_flask_never_saw_any_of_them` | **Skipped** | No `logs/flask.log` file; gunicorn logs to stdout. |

**Did everything pass?** Yes — **after** fixing the environment (`SECRET_KEY`). Not because nginx returned 404 alone; because Flask returned 404 for unknown routes.

**What did our setup let through?**

- Requests **reached gunicorn** (visible in `docker compose logs app`).
- With a bad deploy (no secret key), we briefly **let through 500 errors** — worse than 404 (signals misconfiguration and fills error logs).
- We did **not** get 200/302 on WordPress/`.env` paths — no fake “success” for attackers.

To align with the study guide’s *intent* (block before Flask), add nginx `return 404` rules for paths in `attack_paths.json` above `location /`.

---

## The trust boundary (database on the Docker network only)

### What does that protect against?

In `docker-compose.prod.yml`, the `db` service has **no `ports:`** mapping to the host. Only `app` (and other containers on the same Compose network) can reach `db:5432`.

That protects against:

- **Random internet hosts** connecting to your Postgres port (no public `5432` on the VM).
- **Drive-by scanning** for open databases on your server’s IP.
- **Accidental exposure** when you forget to firewall — the port is not published on `0.0.0.0`.

### What does it *not* protect against?

- **A compromised `app` container** — it can still talk to `db` with the credentials in `DATABASE_URL`.
- **SQL injection or bad queries in Flask** — network isolation does not fix application bugs.
- **Weak DB password** (`app`/`app` in dev) — anyone who *can* reach the network can try it.
- **Other containers on the same Docker network** if you add more services later.
- **Insider / stolen `.env`** — secrets in the app container still unlock the DB.

### What is still your responsibility at the database layer?

Even with the network boundary, the team still owns:

- **Strong passwords** and secrets (not `app`/`app` in real production).
- **Parameterized queries** / ORM usage (no raw SQL with user input).
- **Least privilege** DB users (read-only roles where possible).
- **Backups** and restore testing (`postgres-data` volume).
- **Migrations** and schema constraints (CONTRACTS.md / SQLModel).
- **Row-level ownership** (`current_user.id` on meal plans, etc.).

**Simple analogy:** Hiding the database behind an internal door stops strangers on the street. It does not stop a burglar who already got into the kitchen (the app).

---

## Rate limiting on auth endpoints

Our nginx config (`deploy/nginx/nginx.conf`) uses:

```nginx
limit_req_zone $binary_remote_addr zone=login:10m rate=5r/m;
```

and applies it to:

- `location = /login`
- `location = /login/github`
- `location = /auth/github/callback`

### Which endpoints should also be rate-limited?

| Endpoint | Why |
|----------|-----|
| **`POST /register`** | Account-creation spam, quota abuse. |
| **`POST /login`** | Password guessing (GET is already limited on `/login`). |
| **`/test-login`** | Should be **off in production** (`ENABLE_TEST_LOGIN`); if left on, limit aggressively. |

OAuth callback is limited today — good, because it is part of the login flow.

### Suggested rates (starting point)

| Endpoint | Suggested rate | Rationale |
|----------|----------------|-----------|
| `/login` (GET/POST) | **5 req/min per IP** (what we use) | Matches study guide; allows a few typos with `burst=3`. |
| `/register` | **3–5 req/min per IP** | Slightly stricter — signup is rare for real users. |
| OAuth routes | Same zone as login | Shared “auth” bucket is OK for a class project. |

### Too low — what goes wrong?

- **Shared NAT** (school, office, coffee shop): many real users share one IP → innocent people get **429/503** and cannot log in.
- **Mobile networks** change IP less often but corporate NAT is the classic pain.
- **Legitimate retries** during an outage look like an attack.

### Too high — what goes wrong?

- **Password spraying** stays easy (thousands of tries per hour per IP).
- **OAuth abuse** and registration bots cost CPU and database rows.
- Rate limiting becomes **theater** — looks secure but does not slow attackers.

---

## Quick commands

```bash
# Production stack
export SECRET_KEY=your-secret-from-env
docker compose -f docker-compose.prod.yml up -d

# Attack-path test
pytest tests/test_attack_paths.py -v

# See gunicorn access lines for bot paths
docker compose -f docker-compose.prod.yml logs app --tail=20
```
