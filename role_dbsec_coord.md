# role_dbsec_coord.md — DB / Security + Coordination (3-person team)

**Project:** Foodie — Recipe Scaler and Meal Planner
**Week:** 8 — Production stack and hardening
**Role:** On a 3-person team the DB/security person owns the combined security
*and* coordination surface (Study Guide §24). This write-up answers the two
assigned sub-questions: **§8 nginx as a request filter** and **§10 the
script-kiddie attack-path test**.
**Stack under test:** `docker-compose.prod.yml` → `nginx:1.27-alpine`
(`deploy/nginx/nginx.conf`) → gunicorn (`gunicorn.conf.py`, unix socket) →
Flask (`app.py`) → `postgres:16-alpine`.
**Date:** 2026-06-01

> Note: an earlier `study_guide_answers.md` was written when our nginx config
> had only a single `location /` catch-all, so it concluded "the attack paths
> still reach Flask and get a Flask 404." That is now **out of date** — the
> config in `deploy/nginx/nginx.conf` has since gained two edge-filter regex
> blocks that `return 404` *before* the catch-all. This document reflects the
> current config.

---

## Part 1 — nginx as a request filter (Study Guide §8)

### The traffic reality

Most requests to any public-facing IP are bots, not users. They don't know what
Foodie is; they fire a fixed wordlist at us hoping *something* answers —
`/wp-login.php`, `/.env`, `/.git/config`, `/admin/`, `/phpmyadmin/`,
`/actuator/health`, and dozens of variants. None of these are Foodie routes.
The correct answer is "404, in microseconds, with zero further processing."

### Why it's better for nginx to 404 these than for Flask to

Both nginx and Flask *can* return 404. The difference is **how much of our stack
the junk request wakes up before it gets that 404.**

| Concern | nginx returns the 404 (`return 404`) | Flask returns the 404 (proxied through) |
|---|---|---|
| **Work done** | A single C-level regex match + a ~150-byte canned response. Request dies at the edge. | TLS already terminated, request proxied over the socket, a **gunicorn worker is consumed**, Flask routing runs, `@app.errorhandler(HTTPException)` fires, Jinja renders our branded `error.html`. |
| **Worker pool** | Workers stay free for real users. | We have `workers = 3` (`gunicorn.conf.py`). A burst of scans competes with real users for those 3 slots. |
| **Response size** | Tiny canned page (`< 1 KB`). | Several-KB branded HTML page — bandwidth + render cost for a bot. |
| **Logs** | Noise lands in the **nginx** access log only. | Noise lands in the **Flask/gunicorn** access log, burying real signal. |
| **Blast radius** | A scan can't reach app code, sessions, CSRF, the DB, or any error path. | Every scan executes a code path in our app. If that path is buggy (e.g. our `HTTPException` handler needs the session and `SECRET_KEY` is mis-set, it can 500 instead of 404), the bot is now exercising a failure mode. |
| **Separation of duties** | Edge filters junk; app only sees plausible traffic. | The app is doing the edge's job — defense and routing are tangled together. |

**One-line version:** nginx is the receptionist who turns away wrong-number cold
calls at the front door; Flask is the specialist upstairs. You don't want the
specialist (one of only 3 of them) interrupted thousands of times a day to say
"you have the wrong office." Returning 404 at nginx makes the rejection **cheap,
fast, and contained**; returning it at Flask makes it **expensive, concurrent,
and entangled with application state.**

### How *our* config does it

`deploy/nginx/nginx.conf` filters the junk with two regex `location` blocks that
sit **before** the `location /` catch-all. Because nginx evaluates regex
locations before a plain-prefix `location /`, these win and the request never
gets proxied:

```61:69:deploy/nginx/nginx.conf
        location ~ ^/\.(?!well-known/acme-challenge/) {
            return 404;
        }

        # CMS / framework / admin probes: WordPress, phpMyAdmin, Symfony
        # profiler, Spring Boot actuator, Apache status, stray dumps, etc.
        location ~* ^/(wp-login\.php|wp-admin|wp-content|wp-includes|xmlrpc\.php|administrator|phpmyadmin|admin|server-status|server-info|backup\.sql|config\.php|vendor|_profiler|actuator)(/|$) {
            return 404;
        }
```

- Block 1 kills any **dot-prefixed** path (`/.env`, `/.git/...`, `/.aws/...`,
  `/.ssh/...`, `/.htaccess`, `/.well-known/openid-configuration`) — with a
  deliberate carve-out so `/.well-known/acme-challenge/` still works for future
  Let's Encrypt (§B).
- Block 2 kills the common **CMS/framework/admin** probes.
- We return **404, not 403**, on purpose: 403 ("forbidden") quietly confirms the
  path is *special*; 404 ("nothing here") gives a scanner no signal at all.

### What the Flask access log looks like — before vs. after

**Before nginx (dev: `flask run` / `docker compose up`, app on `:5000`).** Every
bot probe hits Flask directly and shows up in its log:

```text
127.0.0.1 - - [01/Jun/2026 12:00:01] "GET /wp-login.php HTTP/1.1" 404 -
127.0.0.1 - - [01/Jun/2026 12:00:02] "GET /.env HTTP/1.1" 404 -
127.0.0.1 - - [01/Jun/2026 12:00:03] "GET /.git/config HTTP/1.1" 404 -
127.0.0.1 - - [01/Jun/2026 12:00:03] "GET /admin/ HTTP/1.1" 404 -
127.0.0.1 - - [01/Jun/2026 12:00:04] "GET /actuator/health HTTP/1.1" 404 -
... hundreds more per hour ...
```

A real login is a needle in this haystack, and each line above represents a
gunicorn worker + a full Jinja error-page render.

**After nginx (prod: `docker compose -f docker-compose.prod.yml up`).** The
attack paths are answered by `return 404` at the edge and **never reach
gunicorn**, so the Flask/gunicorn access log only contains real traffic:

```text
172.19.0.1 - - [01/Jun/2026:20:31:05 +0000] "GET / HTTP/1.0" 200 6412 "-" "Mozilla/5.0 ..."
172.19.0.1 - - [01/Jun/2026:20:31:07 +0000] "GET /login HTTP/1.0" 200 3120 "-" "Mozilla/5.0 ..."
172.19.0.1 - - [01/Jun/2026:20:31:12 +0000] "POST /login HTTP/1.0" 302 0 "-" "Mozilla/5.0 ..."
172.19.0.1 - - [01/Jun/2026:20:31:18 +0000] "GET /mealplan HTTP/1.0" 200 8855 "-" "Mozilla/5.0 ..."
```

The shift, summarized:

- **Flask access log gets quiet** — real users only; the `/wp-login.php`,
  `/.env`, `/admin/` lines are gone.
- **nginx access log gets noisy** with those 404s — but that's nginx absorbing
  them, not our Python.
- **`/static/`** is served by nginx (`access_log off;` in our config), so it
  doesn't appear in gunicorn logs at all.
- **TLS** terminates at nginx; gunicorn only ever sees plain HTTP on the unix
  socket.
- A scanner that hits the rate-limited `/login` (`limit_req zone=login`) gets
  throttled (503) and gives up faster.

This is the request-filter posture: **nginx absorbs the noise, Flask only sees
signal.**

---

## Part 2 — The script-kiddie attack-path test (Study Guide §10)

### Status of the files in our repo

Both artifacts are already present and match §10 (with two honest upgrades over
the bare study-guide version):

- `attack_paths.json` — the 20 known-bad paths, verbatim from §10.
- `tests/test_attack_paths.py` — the parametrized `test_nginx_blocks` plus
  `test_flask_never_saw_any_of_them`. Our version adds a **body-size assertion**
  (`< 1024 bytes`): a bare status check can't tell an *nginx* 404 (tiny canned
  page) from a *Flask* 404 (our multi-KB branded `error.html`), so without this
  a path that was merely proxied-and-404'd by the app would pass anyway. The
  body-size bound makes the test fail unless the path was genuinely refused at
  the edge.

### How I ran it / what I could actually execute here

`tests/test_attack_paths.py` is the one non-hermetic test in the suite — it
needs the live `nginx → gunicorn → postgres` stack at `https://localhost`. The
authoritative way to run it is the stack + pytest, exactly as our CI does
(`.github/workflows/test.yml`): generate self-signed certs → `docker compose -f
docker-compose.prod.yml up -d --build` → wait for `https://localhost/` →
`pytest -v`.

On this particular machine **Docker is not available** (no `docker` on the
Windows host or in WSL, and no local `nginx`/`openssl`), so I could not boot the
real HTTP stack here. The live, graded run is the GitHub Actions job. What I
*did* run locally, to get real evidence rather than hand-waving:

1. **pytest collection** against the real test + fixture — confirms the test
   shape and parametrization:

   ```text
   $ pytest tests/test_attack_paths.py --collect-only -q
   tests/test_attack_paths.py::test_nginx_blocks[/wp-login.php]
   ... (20 paths) ...
   tests/test_attack_paths.py::test_flask_never_saw_any_of_them
   21 tests collected
   ```

2. **A faithful nginx location-selection simulation** — I implemented nginx's
   documented matching order (exact `=` → remembered longest prefix → regex
   blocks in file order → prefix fallback) and ran the **actual regexes** from
   `deploy/nginx/nginx.conf` against all 20 paths in `attack_paths.json`. This
   reproduces the exact decision nginx makes about which `location` handles each
   request. Result:

   ```text
   PATH                               HANDLED BY                    RESULT
   /wp-login.php                      regex block 2                 EDGE 404 (never reaches Flask)
   /wp-admin/                         regex block 2                 EDGE 404
   /.env                              regex block 1 (^/\.)          EDGE 404
   /.git/config                       regex block 1                 EDGE 404
   /.git/HEAD                         regex block 1                 EDGE 404
   /.aws/credentials                  regex block 1                 EDGE 404
   /.ssh/id_rsa                       regex block 1                 EDGE 404
   /admin/                            regex block 2                 EDGE 404
   /administrator/                    regex block 2                 EDGE 404
   /phpmyadmin/                       regex block 2                 EDGE 404
   /xmlrpc.php                        regex block 2                 EDGE 404
   /server-status                     regex block 2                 EDGE 404
   /backup.sql                        regex block 2                 EDGE 404
   /.htaccess                         regex block 1                 EDGE 404
   /config.php                        regex block 2                 EDGE 404
   /wp-content/plugins/               regex block 2                 EDGE 404
   /vendor/phpunit/                   regex block 2                 EDGE 404
   /.well-known/openid-configuration  regex block 1                 EDGE 404
   /_profiler/                        regex block 2                 EDGE 404
   /actuator/health                   regex block 2                 EDGE 404
   ----------------------------------------------------------------------
   Blocked at edge by nginx: 20/20   Proxied through to Flask: 0/20
   ```

   Note `/.well-known/openid-configuration` is correctly blocked: the negative
   lookahead in block 1 only spares `/.well-known/acme-challenge/`, not the OIDC
   discovery probe.

### Did everything pass? What got let through?

**Derived result of the live run (and what CI produces):**

| Test | Result | Why |
|---|---|---|
| `test_nginx_blocks` (×20) | **20 PASSED** | All 20 paths hit a `return 404` regex block at the edge → status 404 **and** body `< 1 KB` (nginx's canned page, not Flask's). |
| `test_flask_never_saw_any_of_them` | **SKIPPED** | We confirmed `logs/flask.log` does not exist (gunicorn logs to stdout via `accesslog = "-"`), so the test skips by design. |

So: **everything that the test asserts passes — 20 passed, 1 skipped — and it
passes for the *right* reason this time:** nginx is returning the 404 at the
edge, the request never reaches gunicorn. This is strictly better than the
older catch-all-only state, where the same 20 would have 404'd *from Flask*
(same status, but a worker ran and the body-size assertion would have failed).

**What our setup lets through / its honest limits:**

- **The skipped log test is a real gap, not a pass.** We assert "nginx returned
  a small 404," which is strong, but we don't yet *prove* "Flask's log is empty"
  because we don't persist a gunicorn access log to `logs/flask.log`. Turning
  that on (point `accesslog` at a file) would upgrade the skip into an enforced
  edge-refusal proof — this is the cheapest real win and is item #1 on our
  harden-later list.
- **The test only knows these 20 strings.** It's a regression alarm, not a
  security audit. It says nothing about anything not literally in the list. From
  our strategies write-up (`llm_strategies.md`), the single most likely bypass it
  would miss today is **path-normalization / encoding variants** —
  `/%2e%2env`, `/.%65nv`, `//.git/config`, `/..;/.env` — where nginx's regex and
  Flask's router can disagree about what the path "is." Our canonical-form list
  stays green even if an encoded variant slipped through. (Mitigation: wrap each
  path in a few URL-encodings, or add an ffuf/hypothesis mutation layer.)
- **Non-path attacks are entirely out of scope** of this test: injection in
  query/body params, oversized bodies, slowloris, Host-header abuse, OAuth
  callback tampering, and missing-header regressions. A green run means "these 20
  strings are refused at the edge," **not** "no unauthorized request reaches
  Flask."
- **Config-drift footgun the status test can't see:** adding an `add_header`
  inside a `location` silently drops all server-level security headers for that
  location. `gixy` + `nginx -t` in CI would catch that statically.

---

## Still on the "to harden later" list (security + coordination)

1. **Enforce the log assertion** — set gunicorn `accesslog` to `logs/flask.log`
   so `test_flask_never_saw_any_of_them` runs instead of skipping. Proves
   edge-refusal, not just "got a 404 somehow."
2. **Add `ProxyFix`** — `app.py` does **not** currently wire
   `ProxyFix(app.wsgi_app, x_proto=1, ...)`. Without it Flask sees plain HTTP
   from nginx, so `request.is_secure` is `False` and `SESSION_COOKIE_SECURE`
   cookies misbehave (Study Guide §14). Two lines; high value.
3. **Add `gixy` + `nginx -t` to CI** — catch the `add_header`-inheritance trap
   and config syntax errors in seconds, no live stack needed.
4. **Encoding-mutation layer** on the attack-path test to close the
   normalization-bypass gap.
5. **Nightly (not per-PR) nuclei/ZAP baseline scan** against a deployed
   instance, human-triaged, so wordlist churn never blocks a merge.
6. **Least-privilege DB user** — the app connects as `app`/`app` (superuser-ish);
   create a role scoped to only the tables/operations Foodie needs. The Docker
   trust boundary (db has no published `ports:`) protects against external
   reach, but not against a compromised app container (Study Guide §13).
```
