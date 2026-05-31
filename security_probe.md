# Security Probe — Week 8 (§24 Combined: DB/Security + Coordination)

**Role:** Server-side / Security  
**Team size:** 3 (combined surface — nginx edge, attack-path tests, deploy pipeline)  
**Probe template used:** §24 (3-person team, combined DB/security + coordination)

---

## What we gave the LLM

- Full `nginx/nginx.conf` server block (rate limiting, security headers, proxy config)
- `attack_paths.json` (20 known scanner paths)
- `.github/workflows/deploy.yml` (tag-driven, test → build → EC2 deploy)
- Secrets handling: GitHub Actions repo secrets → written to `.env` on EC2 via SSH heredoc

App summary: Flask recipe/meal-planner with GitHub OAuth login, Edamam API
calls, Postgres backend, and Playwright e2e tests. Three routes handle
unauthenticated users; everything else requires a session cookie.

---

## (a) Attacks the path-list test would NOT catch

### 1. SQL / ORM injection via form fields

**What the attack looks like:**

```
POST /login HTTP/1.1
Content-Type: application/x-www-form-urlencoded

username=admin'--&password=anything
```

The path `/login` is in our `location` block and gets rate-limited, but the
_content_ of the POST body goes straight to Flask. nginx never inspects
request bodies for injection patterns.

**Does our nginx config block it?** No. `limit_req` throttles the request
rate; it says nothing about the username value. Flask sees the raw body.

**What blocks it instead:** SQLModel / SQLAlchemy's parametrized queries.
Every ORM `.where(User.username == username_value)` compiles to a prepared
statement — the user-supplied value is never interpolated into SQL text.
If anyone ever writes a raw `text("SELECT * FROM users WHERE username = '" +
val + "'")`, the ORM protection disappears. Code review is the backstop.

---

### 2. Slowloris / slow-client attack

**What the attack looks like:**

```python
import socket, time
s = socket.create_connection(("target", 443))
s.send(b"GET / HTTP/1.1\r\nHost: localhost\r\n")
while True:
    s.send(b"X-Slow: header\r\n")   # dribble headers, never finish
    time.sleep(10)
```

The attacker opens many connections that send headers one byte at a time.
gunicorn workers block waiting for the full request, exhausting the worker
pool. No URL path is involved; the attack is at the TCP/HTTP framing layer.

**Does our nginx config block it?** Partially. Our nginx config doesn't set
`client_header_timeout` or `client_body_timeout`. nginx's defaults are 60 s,
which gives slowloris a 60-second window per connection. We also haven't set
`keepalive_timeout` explicitly.

**What to add:**

```nginx
client_header_timeout  10s;
client_body_timeout    10s;
keepalive_timeout      15s;
send_timeout           10s;
```

This limits how long nginx will wait for a slow sender before closing the
connection. With these set, a slowloris connection dies after 10 s instead of
60 s — slowing the attack dramatically.

---

### 3. Oversized request body

**What the attack looks like:**

```bash
# Generate a 100 MB body and POST it to /mealplan
dd if=/dev/zero bs=1M count=100 | curl -X POST https://localhost/mealplan \
  -H "Content-Type: application/octet-stream" --data-binary @-
```

Our nginx config has no `client_max_body_size` directive. nginx's default is
1 MB, which happens to be reasonable, but it isn't explicit and it applies
uniformly to every endpoint — a file-upload endpoint (if we added one) would
need a different limit.

**Does our nginx config block it?** Yes, accidentally. nginx's default 1 MB
limit rejects this. But we should make it explicit and intentional:

```nginx
client_max_body_size 1m;   # in the http block, or per-location for uploads
```

---

### 4. OAuth callback abuse (redirect_uri manipulation)

**What the attack looks like:**

```
https://localhost/login/github
# → GitHub sends code to /auth/github/callback

# Attacker crafts:
https://localhost/auth/github/callback?code=stolen_code&state=tampered
```

This isn't a URL-path attack (the paths are valid Foodie routes) so our
attack-path test gives no coverage here. Authlib validates the `state`
parameter — if it doesn't match what was stored in the session, the callback
is rejected. This protection exists but isn't tested by `test_attack_paths.py`.

**What blocks it:** Authlib's built-in CSRF state validation.  
**What to add to tests:** A Playwright test that tampers with the `state`
parameter on the callback URL and asserts the app rejects it (returns an error,
does not log the user in). This is currently a gap in our e2e suite.

---

### 5. Host-header injection

**What the attack looks like:**

```
GET / HTTP/1.1
Host: evil.com
```

If Flask uses `request.host` to build redirect URLs (e.g., in OAuth callbacks
or `url_for()` calls), a forged `Host` header can redirect users to an
attacker-controlled domain.

**Does our nginx config block it?** Mostly. ProxyFix uses `x_host=1`, which
trusts `X-Forwarded-Host` from nginx, not the raw `Host` from the client.
nginx passes `$host` (which resolves to the `server_name` value when no
`Host` header matches). An attacker hitting nginx directly still sends a
`Host` header nginx doesn't match — the `server_name localhost` block won't
serve it unless the header also says `localhost`.

**Residual risk:** On EC2, if `server_name` is set to `_` (catch-all) instead
of the actual domain, a forged Host flows through unchecked.  
**What to add:** Set `server_name` to the real domain in the EC2 nginx config
and reject unknown hosts with a `default_server` block that returns 444.

---

## (b) Secrets-leakage paths in our deploy

### 1. `.env` written via heredoc over SSH — visible in the runner's process list

In `deploy.yml` lines 136–142, secrets are written to `.env` on EC2 via an
SSH heredoc. The shell command that runs contains the literal secret values.
On most systems, `ps aux` on the EC2 host during that SSH session would show
the command with the env values in the command line.

**What to change:** Pass secrets as environment variables to the SSH command
rather than embedding them in the shell string:

```yaml
- name: Deploy on EC2
  run: |
    ssh -i ~/.ssh/deploy_key \
        -o SendEnv=SECRET_KEY \
        -o SendEnv=GITHUB_CLIENT_SECRET \
        ${{ secrets.EC2_USER }}@${{ secrets.EC2_HOST }} \
        "env | grep SECRET_KEY > .env"
```

Or better: use AWS Secrets Manager / SSM Parameter Store and pull secrets on
the EC2 host at startup, eliminating the `.env` file entirely.

### 2. `ENABLE_TEST_LOGIN=1` hardcoded in the test job

The `test` job sets `ENABLE_TEST_LOGIN: "1"` so the backdoor routes are
active during CI. This is correct for testing. The risk is if someone
accidentally copies the CI env block into the deploy job — then the
production container runs with the test backdoor open.

**What to change:** Add a step in the `deploy` job that asserts
`ENABLE_TEST_LOGIN` is not set (or is `0`) before `docker compose up`.

### 3. DB password hardcoded in `docker-compose.yml`

`DATABASE_URL: postgresql://app:app@db:5432/app` — the Postgres password
`app` is committed to the repo. On a public GitHub repo, anyone who reads
the file has the DB password. Because `db` has no `ports:` mapping, direct
external access is blocked, but a compromised app container would have it.

**What to change:** Reference `${POSTGRES_PASSWORD}` from secrets, or
accept it as an env var rather than embedding it in the URL literal.

### 4. Docker Hub image is public

Our workflow pushes to `$DOCKERHUB_USERNAME/foodie`. If this is a public
Docker Hub repo, anyone can pull the image and inspect its layers, environment
baked in at build time, and installed packages. We don't bake secrets into
the image (they come from `.env` at runtime) — so this is low risk as-is,
but worth noting.

**What to change:** Use a private Docker Hub repo, or switch to AWS ECR which
is private by default and ties access to IAM roles.

---

## (c) What a hostile collaborator with commit access could do

Worst-case scenario: a teammate's GitHub account is compromised, and the
attacker has push access to the repo.

**Exfiltrate secrets on the next deploy:**
Push a malicious commit that adds `echo $SECRET_KEY` to the deploy job's
run step:

```yaml
- name: Deploy on EC2
  run: |
    echo "KEY=${{ secrets.SECRET_KEY }}"   # ← malicious addition
    ssh ...
```

GitHub Actions tries to redact known secrets in log output, but if the key is
base64-encoded first (`echo ${{ secrets.SECRET_KEY }} | base64`) the encoded
form isn't redacted. Push + tag `v0.8.1` and the secret appears in the public
Actions log.

**Deploy a backdoored image:**
Modify the Dockerfile or `app.py` to add a route that dumps environment
variables or executes arbitrary commands, push, tag, and the poisoned image
deploys to production in the next CI run.

**What mitigates this:**
- Require PR reviews before merges to `main` (branch protection).
- Require 2+ reviewers to approve any workflow file changes (add
  `.github/workflows/` to CODEOWNERS and protect it specifically).
- Use GitHub's "Required reviewers" on Environments so the `deploy` job
  requires a named person to approve before it runs.
- Monitor Actions runs for unexpected steps (Dependabot and similar tooling
  help here).
- Rotate secrets immediately if a teammate's account is suspected compromised.

---

## (d) What's missing from a production-grade deploy

| Gap | Impact | Recommended fix |
|-----|--------|-----------------|
| No health check before routing traffic | A broken deploy starts taking traffic immediately, users see errors | Add a `/health` route to Flask; update nginx to probe it; only swap traffic when probe passes |
| No rollback automation | A bad deploy requires manual re-tagging and re-run | Add a GitHub Actions "rollback" workflow triggered by tag `v*-rollback` that redeploys the previous image tag |
| No deploy notifications | Team doesn't know a deploy happened or failed without checking Actions | Add a Slack/email notification step as the last job in the workflow |
| No blue/green or canary | Deploy swaps 100% of traffic instantly | Run two stacks (`blue` and `green`); shift traffic via nginx `weight` in the upstream block |
| No DB migration step | Schema changes in the app image may not match the live DB | Add `docker compose exec app flask db upgrade` (or equivalent SQLModel migration) before `up -d` |
| No cert renewal | Self-signed cert expires in 365 days; Let's Encrypt expires in 90 days | Certbot with `--deploy-hook "docker compose exec nginx nginx -s reload"` as a cron job |
| No request-size limit set explicitly | nginx's default 1 MB is accidental, not intentional | Add `client_max_body_size 1m;` explicitly in the http block |
| No slow-client timeout | Slowloris can tie up workers | Add `client_header_timeout`, `client_body_timeout`, `keepalive_timeout` |

---

## What we'd push back on / fact-check

- **Host-header injection via ProxyFix** — the LLM flagged this as a risk, but
  our `x_host=1` setting combined with nginx's `server_name localhost` check
  means nginx drops requests with non-matching Host headers before they reach
  Flask. The risk is real on a misconfigured EC2, not on our current setup.

- **OAuth state validation** — the LLM asserted Authlib validates the state
  parameter. We verified this is true (Authlib raises `OAuthError` on a
  missing or mismatched state) but we have no test asserting this. It belongs
  on our e2e backlog, not as a present vulnerability.

- **SQL injection** — the LLM warned about raw SQL. We reviewed `app.py` and
  every query goes through SQLModel's ORM interface. The risk is low as long
  as no one introduces `text()` queries with string interpolation. Worth a
  code-review checklist item.

---

## What's still on the "to harden later" list

1. Explicit `client_max_body_size`, slow-client timeouts in nginx.conf
2. Playwright test for OAuth callback state-tampering rejection
3. `server_name` hardened to real domain (not `_` catch-all) on EC2
4. Secrets via SSM Parameter Store instead of SSH heredoc
5. GitHub Environment with required reviewer on the `deploy` job
6. `/health` endpoint + nginx upstream health check
7. Let's Encrypt cert + Certbot renewal cron (Week 9)
