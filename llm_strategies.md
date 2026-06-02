# Test Strategies for the "Did nginx block the bad paths?" Problem

A conversation about how else you could test the thing
`tests/test_attack_paths.py` tests, what each strategy catches that the
parametrized-path approach doesn't, and what it misses. Study Guide §10 + §24.

Context for the conversation: our provided test is a pytest file that loads a
20-entry `attack_paths.json`, parametrizes over it, and asserts nginx returns
404/403 with a sub-1KB body (so a Flask-served 404 fails the test) for each
path.

---

## Me

We have one attack-path test: pytest parametrized over a fixed list of 20
known-bad URLs, asserting nginx returns 404/403 at the edge. What *other*
strategies exist for testing "the edge refuses what it should"? For each, be
honest about what it catches that our list-based test doesn't, and what it
still misses.

## LLM

Your test is a **known-bad allowlist-of-failures** test. It's a great smoke
test but it only ever proves things about the 20 strings you wrote down. Here
are the other families, roughly in order of how different they are from what
you have:

**1. Scanner integration (nikto / nuclei / OWASP ZAP baseline / gobuster).**
Point a real recon tool at `https://localhost` and assert it finds nothing
interesting. These tools ship with thousands of templates and wordlists that
are kept current by a community.

- *Catches that yours doesn't:* paths you never thought to add — the long tail
  of `/.svn/`, `/.DS_Store`, `/wp-json/`, `/telescope/`, `/.env.bak`,
  thousands of them. nuclei also checks for *responses* (exposed `.git` that
  actually serves objects, default credentials, version-leaking headers), not
  just status codes.
- *Misses:* anything requiring app-specific knowledge (your real routes, your
  auth flow). Scanners are noisy, slow, and flaky in CI; a wordlist update can
  turn a green build red for reasons unrelated to your change. They test
  "what's commonly bad," not "what's bad *for this app*."

**2. Fuzzing (ffuf / wfuzz for paths, RESTler / schemathesis for the API).**
Generate huge numbers of inputs — random paths, mutated paths, malformed
encodings (`/%2e%2e/`, `/..%2f`, null bytes, overlong UTF-8) — and look for
anything that *doesn't* get refused.

- *Catches that yours doesn't:* encoding/normalization bypasses. Your list has
  `/.env` but does `/%2e%2env` or `/.%65nv` or `//.env` or `/./.env` also get
  blocked? A fuzzer finds the case where nginx's regex and Flask's router
  disagree about what a path *is*. This is exactly the class of bug a static
  string list cannot see.
- *Misses:* semantic correctness. A fuzzer knows "this returned 500, weird" but
  not "this leaked another user's meal plan." It's a firehose; triage cost is
  real, and it won't tell you *why* something is wrong.

**3. Property-based / structural tests (hypothesis, or a custom allowlist
test).** Instead of testing a denylist, test an invariant. The strongest
version: enumerate every route your Flask app actually declares
(`app.url_map`), then assert that **any path outside that set returns 404 from
nginx**, generating random outside-paths with hypothesis.

- *Catches that yours doesn't:* this inverts the logic from "these 20 are
  blocked" to "everything not-a-real-route is blocked." That's much closer to
  the real security property. It catches a new attack path the day it's
  invented, because you never had to list it.
- *Misses:* it's only as good as your "real routes" oracle, and it tends to
  over-promise — plenty of non-route paths *should* still reach Flask (static
  files, OAuth callbacks). You end up encoding exceptions, and the test gets
  subtle. It also still doesn't cover *non-path* attacks (method, headers,
  body).

**4. Behavioral / log-assertion tests.** Assert not just the response code but
that the request *never woke Flask* — check the gunicorn/Flask access log
contains none of the bad paths. Your repo already has the skeleton of this
(`test_flask_never_saw_any_of_them`), it just skips unless `logs/flask.log`
exists.

- *Catches that yours doesn't:* the difference between "nginx returned 404" and
  "nginx proxied it, Flask returned 404." A status-only check can't tell those
  apart; the log check proves the request was refused *at the edge*. (Your
  body-size < 1KB heuristic is a clever proxy for this, but a log assertion is
  the real thing.)
- *Misses:* still path-list-bound. It only checks the 20 strings against the
  log. And it depends on log format/retention being stable.

**5. Config-as-artifact tests (gixy, `nginx -t`, golden/snapshot tests).**
Lint the nginx config itself (gixy finds SSRF/`add_header` inheritance traps),
run `nginx -t` in CI to catch syntax errors, and/or snapshot the rendered
config so an unintended diff fails review.

- *Catches that yours doesn't:* the classic `add_header` footgun — adding an
  `add_header` inside a `location` *silently drops all the server-level
  security headers for that location*. A path-status test won't notice your
  HSTS/CSP vanished on `/login`. gixy catches it statically. It also catches
  config that's broken before the stack even boots.
- *Misses:* runtime behavior. A config can lint clean and still route traffic
  somewhere dumb. It doesn't test the actual request/response.

**6. Continuous / production monitoring (WAF, fail2ban, alerting).** Not a
"test" in the CI sense, but the same goal: ModSecurity/Cloudflare rules, or
fail2ban watching the nginx log and banning IPs that rack up 404s.

- *Catches that yours doesn't:* the live, adversarial, novel stuff — and it
  responds (bans, alerts) instead of just asserting. It's the only one that
  works against attacks invented after your last deploy.
- *Misses:* it's detection/response, not a regression gate. It won't stop you
  from *shipping* a misconfig; it just (maybe) catches the consequences in
  prod. False positives can ban real users.

## Me

Give me the one concrete bypass you think our test is most likely to miss
today.

## LLM

Path normalization. Your `location ~ ^/\.` blocks a literal leading-dot
segment, but bots routinely send `/%2e%2e%2f.env`, `/..;/.env`, `/.%2545nv`,
or double-slashed `//.git/config`. nginx and Flask can normalize these
differently. Your 20-string test sends only the canonical forms, so it would
stay green even if an encoded variant slipped through to Flask. A 10-line ffuf
run with an encoding wordlist, or a hypothesis test that mutates each known-bad
path through URL-encoding, would surface it. That's the highest-value addition
for the least effort.

## Me

Rank what you'd add first if security were higher stakes.

## LLM

1. **Promote the log-assertion test from skip to enforced** (configure
   `accesslog` to a file, or assert on `docker logs`). You already wrote it;
   make it run. Cheapest real win — it proves "blocked at the edge," not just
   "got a 404 somehow."
2. **Add gixy + `nginx -t` to CI.** Catches the `add_header`-drops-headers trap
   and syntax breakage statically, in seconds, no live stack needed.
3. **Add an encoding-mutation layer** to the existing parametrized test (wrap
   each path in a handful of encodings). Closes the normalization-bypass gap
   without adopting a whole fuzzing harness.
4. **Nightly (not per-PR) nuclei/ZAP baseline scan** against a deployed
   instance, with results triaged by a human. Keep it out of the PR gate so
   wordlist churn doesn't block merges.

---

## In my own words

**What strategies exist.** Beyond our parametrized known-bad-path test, the
landscape is: (1) real scanners (nikto/nuclei/ZAP) that bring a huge, maintained
corpus of bad paths and check responses not just codes; (2) fuzzers (ffuf,
schemathesis) that generate mutated/encoded inputs to find normalization
bypasses; (3) property/structural tests that flip the logic to "everything that
isn't a real route must 404," so new attacks are covered without listing them;
(4) behavioral/log tests that prove the request died at nginx and never woke
Flask; (5) config-linting (gixy, `nginx -t`, snapshot tests) that catch
misconfigs like the `add_header` inheritance trap before the stack even runs;
and (6) live monitoring/WAF/fail2ban that detects and responds to novel attacks
in production.

**Why the provided approach is what it is.** It's deliberately the cheapest
test that gives a real signal. It's deterministic (no wordlist churn), fast,
hermetic enough to gate a PR, and readable — every entry is a string a
teammate can understand and extend from their own logs. Its job isn't to prove
"we're secure"; it's to be a **regression alarm**: if someone refactors the
nginx config and accidentally widens `location /` so a known scanner path now
reaches Flask, this test goes red immediately. For that specific job, a 20-line
parametrized test is exactly right, and the body-size assertion is a nice touch
that upgrades it from "got a 404" to "got nginx's 404."

**What it doesn't catch.** Anything not literally in the list: encoded/
normalized variants of the same paths, the long tail of scanner paths we didn't
write down, and — more importantly — every attack that isn't a fixed URL string
at all: SQL/template injection in query params or form bodies, oversized
request bodies, slowloris, host-header abuse, OAuth callback tampering, missing
security headers, and auth/authorization logic bugs. A green run here means
"these 20 strings are refused at the edge," not "no unauthorized request
reaches Flask."

**What I'd add if security were higher stakes.** First, turn on the log
assertion we already have (point gunicorn `accesslog` at a file) so the test
proves edge-refusal, not just a 404. Second, add `gixy` and `nginx -t` to CI to
catch the `add_header`-drops-server-headers trap and syntax errors statically.
Third, wrap the existing parametrized paths in a few URL-encodings to close the
normalization-bypass gap. Then, out of the PR critical path, a nightly nuclei
or ZAP baseline scan against a deployed instance, triaged by a human. The first
three are an afternoon of work and meaningfully raise the floor; the scanner is
ongoing operational cost and belongs in a nightly job, not the merge gate.

---

## Future security additions (beyond the edge-test work)

The strategies above are all about *testing the edge refuses what it should*.
Stepping back to the whole app, here's what I'd add next that **isn't** already
on our harden-lists (`role_dbsec_coord.md`, `llm_probe_dbsec.md`), grounded in
this repo. The already-listed items — log-assertion enforcement, `gixy` +
`nginx -t`, encoding-mutation tests, nightly nuclei/ZAP, `ProxyFix`,
least-privilege DB user, cert exclusion from the image, `SECRET_KEY`
fail-closed, the OAuth-linking fix, dep pinning, branch protection + scoped CI
secrets, and rate-limiting `/register` — still stand; these are *additional*.

### Pipeline / supply-chain (cheap, high-leverage)

- **`pip-audit` + Dependabot in CI** — we pin some deps but nothing scans them
  for known CVEs. This is the dependency-level complement to the scanner family
  in §1 above (which only scans *paths*).
- **`bandit` (Python SAST) + `semgrep`** — static analysis catches what no
  path/edge test can: the `@csrf.exempt` on `recipes_scale`, the `SECRET_KEY`
  default fallback in `app.py`, and `debug=True` in the `__main__` block. Think
  of it as a 7th strategy family: *lint the app code*, not just the config.
- **Secret scanning (`gitleaks`/`trufflehog`)** — pre-commit hook + CI gate so a
  `.env` or `deploy/nginx/certs/*.pem` can never be committed. Our attack list
  already treats `.env` / `.aws/credentials` as crown jewels; this stops them
  leaking at the source.

### Container / runtime hardening

- **Run the app as non-root.** `Dockerfile.prod` has no `USER` directive, so
  gunicorn runs as root. Add a non-root `USER`, plus `read_only: true`,
  `cap_drop: [ALL]`, and `security_opt: [no-new-privileges]` in
  `docker-compose.prod.yml`.
- **Image scanning** — Trivy/Grype on the built image in CI.

### App / auth (the layer no edge test reaches)

- **Account-level lockout / backoff.** Our `limit_req zone=login` is *per-IP*, so
  password spraying from a botnet (one try per IP) sails past it. Add per-account
  failed-attempt backoff.
- **Server-side sessions + session rotation on login.** Flask's default is a
  client-side signed cookie — unrevocable, no "log out everywhere." A server-side
  store (e.g. Redis) plus regenerating the session id on login closes
  session-fixation and enables revocation.
- **Tighten CSP** — `nginx.conf` still allows `'unsafe-inline'` in `style-src`.
  Move to hashes/nonces and add a CSP `report-uri` so violations are a signal.
- **Fix the image-proxy SSRF TOCTOU.** `_safe_remote_image_url()` resolves DNS,
  then `_fetch_remote_image()` connects separately — a DNS-rebind window. Pin the
  validated IP for the actual fetch, or use an egress allowlist.

### Secrets / infra (we deploy on AWS — `boto3` is in `requirements.txt`)

- **Move secrets out of `.env` into AWS Secrets Manager / SSM Parameter Store**,
  with rotation for `SECRET_KEY` and the OAuth client secret. Document a
  key-rotation runbook (rotating `SECRET_KEY` invalidates all sessions).
- **IAM instance roles instead of long-lived AWS keys**, IMDSv2 enforced,
  locked-down security groups.
- **TLS for the DB connection** — `DATABASE_URL` is plaintext `postgresql://`
  over the Docker network; add `sslmode=require`.

### Detection / response & process

- **Centralized logs + alerting** on 401/403/500 spikes and failed-login bursts
  (extends the WAF/fail2ban idea in §6 from "block" to "observe + alert"), plus
  an **auth audit log** (login, OAuth link, logout).
- **A written STRIDE threat model** — `llm_probe_dbsec.md` is effectively an
  informal one; formalizing it makes coverage gaps explicit.

**Top 5 to do next:** `pip-audit` + Dependabot, `bandit`/`semgrep`, non-root
container, per-account login backoff, and moving secrets into AWS Secrets
Manager.

---

## Mobile: different security considerations if Foodie becomes a phone app

We're weighing turning Foodie into a phone app. The short version: **going
mobile changes the *authentication model* more than anything else, and that
ripples through most of our current controls.** How much depends on which kind:

- **Native iOS/Android app** talking to our Flask backend as a JSON API — the
  biggest shift (covered below).
- **PWA / mobile-optimized web** (same Flask, responsive UI) — much lighter;
  cookies, CSRF, and the nginx edge carry over largely unchanged.

### The big one: cookies/CSRF → tokens

Today we authenticate with Flask-Login **session cookies** + global
`CSRFProtect` (`app.py`). A native app can't ride browser cookies cleanly, so
we'd move to a **token-based API**: OAuth2 Authorization Code **+ PKCE**, issuing
short-lived access tokens + rotating refresh tokens.

- **CSRF mostly goes away** for a pure bearer-token API (no ambient cookie = no
  cross-site forgery), so the `@csrf.exempt` on `recipes_scale` stops being a
  smell — but we trade it for **token theft / storage** risk.
- **Token revocation becomes mandatory.** Our sessions are client-side signed
  cookies with no server-side store; with long-lived refresh tokens on a
  losable/rootable device, a **server-side token store with rotation +
  reuse-detection** moves from nice-to-have to required.

### Secrets can't live in the app binary

APKs/IPAs are decompilable, so:

- **No OAuth `client_secret` on device** — mobile is a *public* OAuth client;
  use **PKCE** and treat the client as untrusted. `OAUTH_CLIENT_SECRET` stays
  server-side only.
- **No Edamam keys in the app.** We already proxy Edamam server-side through
  Flask — exactly right; keep every third-party key behind the backend.

### OAuth redirect / deep-link hijacking

Mobile redirects return via a URL scheme or app link that **other apps can try
to claim**. Mitigate with **PKCE**, **claimed HTTPS App Links / Universal
Links** (not `myapp://` schemes), and `state` validation. Our web open-redirect
guard (`startswith("/") and not //`) doesn't translate.

### Transport & a client we can't trust

- **Real TLS certs required** (iOS ATS rejects our self-signed dev cert);
  consider **certificate pinning** with a rotation plan.
- **We can't patch the client instantly** — users run old versions for months.
  So: **version the API**, enforce everything server-side, and keep a
  **force-upgrade / kill-switch** for clients with known vulns.
- **Assume a hostile device:** rooted/jailbroken phones, user-installed MITM
  CAs, tampered binaries. Store tokens in **iOS Keychain / Android Keystore**,
  never plaintext. Optionally **device attestation** (App Attest / Play
  Integrity) for sensitive calls.

### Easier on mobile
- CSRF largely disappears for token APIs.
- DOM-XSS surface shrinks for native UI — unless a WebView reintroduces it (and
  our CSP only protects the web path).

### Unchanged / still applies
- nginx **edge filter, rate limiting, TLS termination, headers** still front the API.
- **Server-side authorization** (`current_user.id` ownership checks) — *more*
  important now that the client is fully untrusted.
- **Image-proxy SSRF guard, DB trust boundary, least-privilege DB user** — same.
- The **OAuth account-linking bug** (`llm_probe_dbsec.md`) is worse on mobile
  (account takeover) — fix before expanding surface.

### New, mobile-specific
- **Platform privacy/permissions:** app-store data-disclosure labels, runtime
  permission prompts, minimize PII.
- **Push notifications:** no sensitive data in payloads; secure the device-token
  registration endpoint.
- **Rate-limit by account/token, not just IP** — mobile roams across IPs
  (cellular ↔ wifi), so per-IP limits both over- and under-block.

**Top 3 before writing any mobile code:** (1) design the **token model** —
short access + rotating refresh tokens with a **server-side revocation store**;
(2) **mobile OAuth = public client + PKCE**, no secrets/keys in the binary (keep
proxying Edamam); (3) **secure on-device token storage + real TLS** (decide on
cert pinning).

what else do you recommend to ass to security in the future?