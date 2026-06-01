# LLM Probe — Backend Layer (§22)

**Role:** Backend / Server-side  
**Probe template:** Study Guide §22  
**Configs pasted:** `gunicorn.conf.py`, Flask app config block (lines 58–82), error handler, `if __name__` entry point

---

## What I pasted in

**gunicorn.conf.py** (full file):

```python
bind             = "unix:/tmp/gunicorn.sock"
workers          = 3
worker_class     = "sync"
timeout          = 30
graceful_timeout = 30
accesslog        = "-"
errorlog         = "-"
loglevel         = "info"
max_requests     = 1000
max_requests_jitter = 50
preload_app      = True
```

**Flask production config block:**

```python
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-not-for-production")
app.config["REMEMBER_COOKIE_DURATION"]  = timedelta(days=30)
app.config["REMEMBER_COOKIE_HTTPONLY"]  = True
app.config["REMEMBER_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "").lower() in (
    "1", "true", "yes",
)

csrf = CSRFProtect(app)
```

**Entry point:**

```python
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
```

**Error handler:**

```python
@app.errorhandler(HTTPException)
def handle_http_exception(e: HTTPException):
    code = e.code or 500
    ...
    return render_template("error.html", ...), code
```

---

## Prompt sent

> Audit this for production readiness. Identify:
> (a) Settings that are wrong or absent for production.
> (b) Information-leakage paths — tracebacks, error messages, default
>     endpoints that leak framework details.
> (c) Anything that would behave correctly under flask run but break
>     (or behave differently) under gunicorn, or vice versa.
> For each, tell me what you'd change and why.

---

## What the LLM found

### (a) Settings wrong or absent for production

**1. ProxyFix is missing.**  
The app is deployed behind nginx, which terminates TLS and forwards plain HTTP
to gunicorn. Without `ProxyFix`, Flask sees `request.scheme = 'http'` and
`request.is_secure = False` on every request, even though the user is on HTTPS.
This has two visible effects: `url_for()` generates `http://` links when called
with `_external=True`, and `SESSION_COOKIE_SECURE` — even when set to `True`
via the env var — refuses to set the cookie because Flask thinks the connection
is insecure. The fix is two lines before the config block:

```python
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
```

`x_proto=1` tells ProxyFix to trust one upstream proxy's `X-Forwarded-Proto`
header — namely nginx. After this, `request.scheme` is `'https'` and the
Secure cookie flag activates correctly.

**2. `SESSION_COOKIE_SECURE` is opt-in via env var, not always-on.**  
The current code:
```python
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "").lower() in (
    "1", "true", "yes",
)
```
If the env var is missing or mis-spelled on the production host, `SECURE` is
silently `False` and the session cookie goes out over HTTP. This is a
misconfiguration that fails open (insecure) rather than failing closed. With
ProxyFix in place, `SESSION_COOKIE_SECURE = True` should be unconditional —
the only reason to ever turn it off is local dev without HTTPS, and that's
handled better by a separate dev config than an env-var toggle.

**3. Secret key fallback is a committed default.**  
```python
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-not-for-production")
```
If `SECRET_KEY` is not set in production, Flask runs with a known fallback.
Anyone who reads the source (the repo is public on GitHub) can forge session
cookies signed with that key. The safe pattern is to raise at startup if the
key is absent:
```python
SECRET_KEY = os.environ["SECRET_KEY"]  # KeyError crashes loudly at startup
```
A loud crash at startup is better than silently running insecure.

**4. `debug=True` in the entry point.**  
```python
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
```
This is only reached when the file is run directly (`python app.py`), not when
gunicorn imports it — gunicorn calls `app:app`, which imports the module
without executing `__main__`. So in the gunicorn deployment, `debug=True`
never fires. However, if anyone on the team accidentally runs `python app.py`
on a machine with a public IP, they've exposed the Werkzeug interactive
debugger. Better practice is to read debug from an env var:
```python
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000,
            debug=os.environ.get("FLASK_DEBUG", "0") == "1")
```

### (b) Information-leakage paths

**Custom error handler returns rendered HTML, not raw tracebacks.**  
The `@app.errorhandler(HTTPException)` handler renders `error.html` with a
friendly message. Flask's default in production (non-debug) mode also returns
plain HTML without a traceback — so there's no regression here. The handler
is doing the right thing.

**`/api/debug/oauth-identity/<username>` endpoint.**  
This route returns a user's `github_id` and `github_login` from the database,
gated by `ENABLE_TEST_LOGIN=1`. If that env var is accidentally set in
production, the route is live and leaks OAuth identity data for any username an
attacker knows. It should be removed entirely before a real production deploy,
not just gated behind an env var.

**gunicorn logs to stdout (`accesslog = "-"`).**  
This is correct — Docker captures stdout. The risk is if a logging pipeline
downstream collects these logs and stores them insecurely. Access logs include
request paths and query strings. If any endpoint encodes a secret in a query
parameter (OAuth `code`, password reset token), it appears in the access log.
None of Foodie's current routes do this, but it's worth knowing.

### (c) Behaves under flask run but breaks under gunicorn

**`preload_app = True` and module-level side effects.**  
With `preload_app = True`, gunicorn imports `app.py` once in the master process,
then forks workers. Any module-level code (including `SQLModel.metadata.create_all(engine)`)
runs once before the fork, which is fine — SQLAlchemy engines are designed to be
fork-safe as long as you don't hold an open connection across the fork boundary.
Under `flask run`, the app is imported fresh in a single process with no forking.
The difference: if any library holds shared state that isn't fork-safe (file
handles, socket connections opened at import time), it would silently corrupt
under gunicorn but work fine under `flask run`. Our codebase doesn't do this,
but it's the reason the gunicorn docs warn about `preload_app`.

**Unix socket binding.**  
`bind = "unix:/tmp/gunicorn.sock"` creates a socket at that path. Under
`flask run`, the app listens on a TCP port. The difference only matters if you
try to run the gunicorn config locally without the shared Docker volume mounted
at `/tmp` — the socket path won't exist and gunicorn will fail to bind. Not a
production problem, but a gotcha for local testing outside Docker.

---

## The four required questions

### Why gunicorn, concretely — three disqualifying properties of `flask run`

**1. Single-threaded.**  
`flask run` handles one request at a time. Request 2 waits for request 1 to
finish. On any endpoint that hits the Edamam API (which can take 1–2 s),
the second user's request is just blocked. With gunicorn's 3 workers, three
requests are in-flight simultaneously. This isn't a nice-to-have; it's the
minimum to not feel broken under light real-world load.

**2. Interactive debugger.**  
`flask run --debug` activates Werkzeug's pin-protected interactive debugger.
If an unhandled exception occurs on a public-facing deployment, any user who
triggers that exception sees a traceback in their browser and — after entering
the debugger PIN — gets a live Python REPL with access to the running process,
its memory, and its environment variables. This is a remote code execution
endpoint. gunicorn has no equivalent. Unhandled exceptions log to stderr and
return a plain 500.

**3. No graceful restart.**  
When you redeploy with `flask run`, you kill the process and start a new one.
Any in-flight requests are dropped. gunicorn's `graceful_timeout = 30`
means workers finish their current requests before dying — a deploy under load
doesn't disconnect active users.

---

### Worker model

For Foodie's traffic pattern: a class project with a handful of concurrent users,
routes that do one or two Postgres queries per request, and some routes that call
the Edamam API (1–2 s round-trip, blocking).

**I'd pick `sync` with 3 workers, as currently configured.**  
The Postgres queries are fast (< 10 ms). The Edamam API calls are slow but
infrequent (only on recipe search). With `sync` and 3 workers, 3 recipe searches
can block simultaneously without affecting the rest of the app. At the scale of
a class project that's more than enough headroom.

**What would change my mind to `gthread`:**  
If profiling showed that workers spend > 50% of their time waiting on the Edamam
API or GitHub OAuth redirects — i.e., I/O-bound, not CPU-bound — switching to
`gthread` with `threads = 4` would let each worker handle up to 4 concurrent
I/O-bound requests instead of 1. The cost is slightly higher memory and needing
to confirm every library used is thread-safe (Flask and SQLAlchemy are; most
Python libraries are).

**`gevent` is off the table** unless we've audited every dependency for async
safety, which we haven't. It monkey-patches the standard library at import time,
which can silently corrupt any library that assumes synchronous I/O.

---

### The WSGI contract

WSGI is a Python standard (PEP 3333) that defines a single function signature:

```python
def application(environ: dict, start_response: callable) -> Iterable[bytes]:
    ...
```

`environ` is a dict of request data (method, path, headers, body). `start_response`
is a callback for sending the status code and headers. The return value is an
iterable of response body bytes.

Flask's `app` object implements this signature — calling `app(environ, start_response)`
is valid Python. gunicorn implements the other side: it knows how to construct
`environ`, call any WSGI-conforming object, and send the returned bytes to the
client.

**Why this matters beyond gunicorn:**  
The contract is the seam. If we switched from gunicorn to uWSGI, mod_wsgi, or
Waitress, the Flask code changes nothing — those servers also implement the WSGI
caller side. The framework and the server are independently swappable as long as
both respect the contract.

**What would change with ASGI:**  
ASGI (Async Server Gateway Interface) is the async successor to WSGI, used by
FastAPI and Django's async views. If we switched to an ASGI framework, we'd
need an ASGI server (Uvicorn, Hypercorn) instead of gunicorn. Flask (up to 3.x)
is WSGI-only — the app object doesn't conform to the ASGI signature. A framework
switch would require rewriting route handlers but the *pattern* — a contract
between server and framework expressed as a callable signature — is the same idea.

---

### ProxyFix and X-Forwarded-Proto

**What breaks without ProxyFix:**  
nginx terminates TLS and forwards the request to gunicorn over plain HTTP on
the unix socket. From gunicorn's perspective it received an HTTP request —
that's what it passes to Flask. Flask sets `request.scheme = 'http'` and
`request.is_secure = False`. Consequences:

- `url_for('login', _external=True)` generates `http://` links.
- `SESSION_COOKIE_SECURE = True` refuses to set the session cookie, because Flask
  considers the connection insecure. Login is silently broken — the cookie is
  never sent, so the user appears logged out on every request after the
  login POST.
- Any code that branches on `request.is_secure` behaves as if on plain HTTP.

nginx does set `X-Forwarded-Proto: https` in our config:
```nginx
proxy_set_header X-Forwarded-Proto $scheme;
```
But Flask doesn't trust that header by default. Any HTTP client can set any
header — if Flask blindly trusted `X-Forwarded-Proto`, an attacker could send
`X-Forwarded-Proto: https` directly to gunicorn (if gunicorn were somehow
reachable) and bypass HTTPS-only logic.

**What ProxyFix does:**  
`ProxyFix(app.wsgi_app, x_proto=1)` wraps the WSGI environ before Flask sees
it. It reads `X-Forwarded-Proto`, trusts it (because `x_proto=1` says "trust
one upstream proxy"), and rewrites `wsgi.url_scheme` in the environ to `https`.
Flask then reads the corrected environ and sets `request.scheme = 'https'`.

**Why it's a Flask concern, not an nginx concern:**  
nginx is behaving correctly — it's forwarding headers faithfully. The mismatch
is in Flask's default assumption that it's the edge server. ProxyFix is an
explicit opt-in that says "you're not the edge, trust this many proxy layers."
Putting this fix in nginx config isn't possible — nginx can't change how Flask
interprets its own environ.

**Finding on this branch:**  
ProxyFix is currently absent from `samuel-hardening`. `SESSION_COOKIE_SECURE`
is also conditional on an env var rather than always-on. Together, this means
login is likely silently broken in the production nginx deployment on this branch:
the secure cookie is never set, users appear logged out after login. This needs
to be fixed before this branch is merged.

---

## What I'd actually fix

1. **Add ProxyFix** — two lines, highest priority.
2. **Make `SESSION_COOKIE_SECURE = True` unconditional** — remove the env-var toggle; it fails open.
3. **Raise `KeyError` if `SECRET_KEY` is missing** — use `os.environ["SECRET_KEY"]` so a misconfigured deploy crashes loudly at startup rather than running with a known-bad key.
4. **Change `app.run(debug=True)` to read from env** — low risk since gunicorn doesn't hit `__main__`, but removes the footgun for anyone running `python app.py` on a public machine.
5. **Remove `/api/debug/oauth-identity/` before production merge** — or hard-delete the route, not just gate it.

## What I'd push back on

The LLM flagged `preload_app = True` as potentially dangerous. It's not wrong —
if any library opens a file handle or socket at import time, forking with
`preload_app` would share that handle across workers and corrupt it. But I reviewed
`app.py` and the only module-level connection is `create_engine(DATABASE_URL)`,
which creates an engine (connection pool config) but doesn't open a real connection
until the first query. SQLAlchemy explicitly supports this pattern.
`preload_app = True` is fine as-is; the LLM's concern applies to a class of code
we don't have.
