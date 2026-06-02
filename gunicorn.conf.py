# gunicorn.conf.py — production config for the WSGI server
#
# Run via Dockerfile (docker compose up):
#   gunicorn -c gunicorn.conf.py app:app

# Where gunicorn listens. Unix socket for nginx on the same host.
bind = "unix:/tmp/gunicorn.sock"
# Alternative for docker-compose with TCP:
# bind = "0.0.0.0:8000"

# Number of worker processes. Rule of thumb: (2 * CPU cores) + 1.
# Adjust based on actual load measurement.
workers = 3

# Worker class. sync is the default and right for most apps.
# Use gthread for I/O-bound apps doing slow external calls.
# Use gevent only if you've thought hard about monkey-patching.
worker_class = "sync"

# Per-worker request timeout. Kills hung workers.
timeout = 30

# How long to let in-flight requests finish during a graceful restart.
graceful_timeout = 30

# Logs to stdout/stderr so Docker captures them.
accesslog = "-"
errorlog = "-"
loglevel = "info"
# gunicorn.conf.py — production config for the WSGI server (Foodie)
#
# Run via Dockerfile CMD:
#   gunicorn -c gunicorn.conf.py app:app
#
# The app module is app.py; the WSGI callable is the module-level Flask
# `app` object (not an app factory).  If you switch to create_app(), use:
#   gunicorn -c gunicorn.conf.py 'app:create_app()'

# ── Binding ───────────────────────────────────────────────────────────────────
# Unix socket shared with the nginx container via a Docker named volume.
# nginx connects to the same path on its side of the shared /tmp mount.
# Alternative for docker-compose TCP networking:
#   bind = "0.0.0.0:8000"
bind = "unix:/tmp/gunicorn.sock"

# ── Workers ───────────────────────────────────────────────────────────────────
# Rule of thumb: (2 × CPU cores) + 1.
# 3 is the right default for a single-core VM or a dev machine.
# Adjust based on actual load measurement — more workers → more memory.
workers = 3

# Worker class: "sync" is correct for a standard Flask app doing blocking I/O
# to Postgres.
# Switch to "gthread" + threads=4 if profiling shows workers spending most of
# their time waiting on external HTTP calls (Edamam API, GitHub OAuth).
# Use "gevent" only if you've audited every library for async safety.
worker_class = "sync"

# ── Timeouts ──────────────────────────────────────────────────────────────────
# Kill a worker if it takes longer than 30 s to serve a single request.
timeout = 30

# How long to let in-flight requests finish during a graceful rolling restart.
graceful_timeout = 30

# ── Logging ───────────────────────────────────────────────────────────────────
# "-" → stdout/stderr.  Docker captures these automatically via `docker logs`.
accesslog = "-"
errorlog  = "-"
loglevel  = "info"

# ── Worker recycling ──────────────────────────────────────────────────────────
# Restart each worker after N requests (±jitter) to defend against memory leaks.
# Jitter spreads the restarts so all workers don't recycle at the same moment.
max_requests        = 1000
max_requests_jitter = 50

# ── App preloading ────────────────────────────────────────────────────────────
# Load the application once before forking workers.  Faster cold start and
# cheaper memory (copy-on-write pages are shared until a worker writes them).
# The module-level SQLModel.metadata.create_all(engine) runs once here,
# not once per worker.  SQLAlchemy engine objects are fork-safe as long as
# you don't open a connection at import time — connections are created lazily
# per-worker after fork, so this is fine.
preload_app = True
