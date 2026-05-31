# gunicorn.conf.py — production WSGI server config for Foodie
#
# Run via Dockerfile CMD:
#   gunicorn -c gunicorn.conf.py app:app
#
# The app module is app.py; the WSGI callable is the Flask `app` object.

# ── Binding ───────────────────────────────────────────────────────────────────
# Unix socket shared with the nginx container via a Docker named volume.
# nginx connects to the same path on its side of the volume mount.
bind = "unix:/tmp/gunicorn.sock"

# ── Workers ───────────────────────────────────────────────────────────────────
# Rule of thumb: (2 × CPU cores) + 1.  3 is a safe default for a 1-core VM.
workers = 3

# sync is correct for a standard Flask app that does blocking I/O to Postgres.
# Switch to gthread + threads=4 if profiling shows workers spending time waiting
# on external HTTP calls (Edamam API, GitHub OAuth).
worker_class = "sync"

# ── Timeouts ──────────────────────────────────────────────────────────────────
timeout = 30           # kill a worker if it takes longer than 30 s per request
graceful_timeout = 30  # let in-flight requests finish during a rolling restart

# ── Logging ───────────────────────────────────────────────────────────────────
# "-" means stdout/stderr — Docker captures these automatically.
accesslog = "-"
errorlog  = "-"
loglevel  = "info"

# ── Worker recycling ──────────────────────────────────────────────────────────
# Restart each worker after N requests (±jitter) to defend against memory leaks.
max_requests        = 1000
max_requests_jitter = 50

# ── App preloading ────────────────────────────────────────────────────────────
# Load the application once before forking workers.  Faster cold start and
# cheaper memory (copy-on-write).  The module-level SQLModel.metadata.create_all
# runs once here, not once per worker.
preload_app = True
