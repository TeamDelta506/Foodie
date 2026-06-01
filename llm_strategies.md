# Test strategies for “script-kiddie” paths and scanner noise

This document compares ways to test that bad URLs (from `attack_paths.json`) are handled safely. It includes notes from working through Study Guide §10 with an LLM on the Foodie stack.

---

## The problem we are testing

Internet-facing apps get constant probes: `/wp-login.php`, `/.env`, `/phpmyadmin/`, etc. We want confidence that:

1. Attackers get **404 or 403**, not 200 with secrets or 500 with stack traces.
2. (Ideally) those requests **do not waste** application workers.
3. Regressions are **caught in CI** when someone changes nginx or Flask.

---

## Strategy 1: Parametrized pytest + `attack_paths.json` (what the study guide provides)

**How it works:** A JSON list of paths; pytest runs one test per path against `https://localhost` and asserts status ∈ `{404, 403}`.

**What it catches that others often miss early:**

- **Obvious regressions** — someone breaks the 404 handler or nginx and deploy still “works” for `/`.
- **Fast, deterministic CI** — no extra tools; runs in seconds.
- **Documented contract** — the JSON file is the team’s shared list of “paths we refuse to serve meaningfully.”

**What it misses:**

- **Paths not in the list** — zero-day probe URLs, framework-specific bugs, typosquatting paths.
- **Whether Flask actually ran** — our stack proxies `location /` to gunicorn; 404 from Flask still **passes** the test.
- **POST / HEAD / weird headers** — test uses `GET` only.
- **Rate limiting, TLS, headers** — not covered.
- **Environment misconfig** — we saw all **500** when `SECRET_KEY` was unset; the test looked like “nginx failure” but root cause was Flask sessions.

**Why the course uses this approach:** Cheap, teachable, runs in every repo without licensing scanners. Good first gate for students.

**What we would add at higher stakes:** nginx `return 404` before `proxy_pass`, log assertion that gunicorn never sees listed paths, plus one dynamic scan job in CI.

---

## Strategy 2: Integration with a web vulnerability scanner (Nikto, OWASP ZAP, Nuclei)

**How it works:** Point a scanner at staging; it crawls and fires thousands of known checks.

**Catches beyond the JSON list:**

- **Huge template libraries** (CVE checks, misconfigs, default files).
- **Header/TLS issues** (HSTS, cookie flags) in the same run.
- **Combo attacks** (e.g. XSS on a form the static list never hits).

**Misses:**

- **Business-logic flaws** (IDOR on `/mealplan`, OAuth state bugs).
- **False positives** — noisy reports need human triage.
- **Flask-only bugs** on routes that require login unless you script auth.
- **“Passes scanner” ≠ safe** — scanners lag new frameworks.

**Honest read:** Best for **breadth** on a deployed URL; poor for proving **your** 20 paths without also maintaining the JSON test.

---

## Strategy 3: Fuzzing (ffuf, wfuzz, boofuzz on HTTP)

**How it works:** Generate or mutate paths (`/admin`, `/api/v1/../`, long strings) and observe status codes, lengths, timing.

**Catches beyond the list:**

- **Unknown paths** that return 200/500/302 when they should not.
- **Parser differentials** (double encoding, `%2e%2e/`).
- **Crashers** — 500s that reveal debug mode.

**Misses:**

- **Semantic authorization** — fuzzer does not know “user A must not see user B’s meal plan.”
- **Stateful flows** (login → CSRF → POST) without heavy scripting.
- **Operational cost** — easy to DoS your own staging if run too hot.

**Honest read:** Finds **weird edge URLs**; weak on **correct behavior** for valid app routes.

---

## Strategy 4: Behavioral / end-to-end tests (Playwright, Cypress)

**How it works:** Browser drives real login, meal plan, OAuth; asserts UI and network tab.

**Catches beyond the list:**

- **Real user flows** after deploy (cookies, HTTPS redirects, CSP breaking Bootstrap).
- **“Login still works under rate limit”** after nginx changes.

**Misses:**

- **20 probe paths** unless you explicitly visit each (duplicates Strategy 1 in a heavier runner).
- **Mass scanning volume** — one browser session is not 10k bots.

**Honest read:** Best for **“does the product work?”** not **“did we block /.env?”**

---

## Strategy 5: Log-based / metrics assertions (“Flask never saw them”)

**How it works:** After a scan, grep gunicorn/nginx logs; alert if `wp-login` appears in app logs or if 404 rate spikes.

**Catches beyond the list:**

- **Misconfigured proxy** — exactly the gap in our current `location /` setup.
- **Production-only issues** (wrong `SECRET_KEY`, broken upstream).

**Misses:**

- **Attacks that never log** (dropped at firewall).
- **Needs reliable log pipeline** — our optional `test_flask_never_saw_any_of_them` skips when `logs/flask.log` does not exist.

**Honest read:** Strong **second line of defense** when paired with nginx deny rules; weak alone without log discipline.

---

## Strategy 6: Infrastructure / config tests (pytest on nginx.conf, conftest, policy-as-code)

**How it works:** Parse `deploy/nginx/nginx.conf` in CI; assert `limit_req` exists, `db` has no `ports`, TLS 1.2+ only.

**Catches beyond the list:**

- **Accidental compose regressions** (someone publishes `5432:5432`).
- **Missing rate limit zone** before merge.

**Misses:**

- **Runtime behavior** — config can be valid but app still returns 500.
- **Does not prove** attack paths are blocked at runtime.

**Honest read:** Fast guardrails on **shape** of security config, not on **outcomes**.

---

## Strategy 7: Manual red-team / peer review

**How it works:** Teammate tries `curl`, Burp, stolen session cookie, `docker compose exec db psql`.

**Catches:**

- **Context** — “this 404 leaks that the app is Flask.”
- **Chained bugs** the automated list will never include.

**Misses:**

- **Repeatability** unless written up as tests afterward.

---

## Summary table

| Strategy | Best at | Weak at |
|----------|---------|---------|
| Parametrized pytest + JSON | Fast regression on known bad paths | Unknown paths; proxy-to-Flask blind spot |
| Scanner (ZAP/Nuclei) | Wide CVE / misconfig coverage | Logic bugs; noise |
| Fuzzing | Weird URLs, crashes | Authz, business rules |
| E2E browser | Real user + TLS + cookies | Bot path volume |
| Log assertions | Proving edge blocked app | Needs logging setup |
| Config tests | Compose/nginx policy | Runtime 500s |
| Manual review | Chains and judgment | Not automatic |

---

## What we learned from the LLM this week (example for your write-up)

**Surprise:** With `SECRET_KEY` unset, every attack-path test returned **500**, not 404. The LLM helped trace that to Flask’s session middleware, not nginx “letting attacks through.”

**Why it mattered:** The pytest message said “nginx let it through to Flask,” but the fix was **operations** (set `SECRET_KEY` in `.env`), not nginx rules. It showed that **green tests depend on deploy env**, not just config files.

**Second surprise:** All 20 tests **passed** while gunicorn access logs still listed `/wp-login.php` and `/.env`. The LLM clarified that our `location /` **proxies everything** — passing status-code tests is not the same as blocking at the edge.

*Edit this section with your own “aha” if a different part stood out to you.*

---

## If security were higher stakes — what we would add

1. **nginx `map` or explicit `location = /wp-login.php { return 404; }`** for everything in `attack_paths.json` *before* `location /`.
2. **CI job** that fails if gunicorn logs contain any path from the JSON after a test run.
3. **Scheduled ZAP baseline** against staging (weekly).
4. **WAF / cloud shield** in front of nginx for volumetric bots.
5. **Separate rate-limit zones** for `register` vs `login` vs OAuth.
6. **Secrets scanning** in git + block `.env` in images.
7. **Managed Postgres** with IAM/network policies instead of only “no ports in compose.”

The provided pytest + JSON approach is the right **first layer** for a course repo: explicit, cheap, and good for teamwork. It is not a complete security program by itself.
