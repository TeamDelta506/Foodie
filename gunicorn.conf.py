# gunicorn.conf.py — production config for the WSGI server (Foodie)
#
# Run via Dockerfile CMD:
#   gunicorn -c gunicorn.conf.py app:app
#
# The app module is app.py; the WSGI callable is the module-level Flask
# `app` object (not an app factory).  If you switch to create_app(), use:
#   gunicorn -c gunicorn.conf.py 'app:create_app()'

import os

# ── Binding ───────────────────────────────────────────────────────────────────
# Render / PaaS: PORT is set → bind 0.0.0.0:PORT (HTTP from the platform router).
# docker-compose.prod + nginx: set GUNICORN_BIND=unix:/tmp/gunicorn.sock (default when PORT unset).
_port = os.environ.get("PORT")
_default_bind = f"0.0.0.0:{_port}" if _port else "unix:/tmp/gunicorn.sock"
bind = os.environ.get("GUNICORN_BIND", _default_bind)

# ── Workers ───────────────────────────────────────────────────────────────────
# Rule of thumb: (2 × CPU cores) + 1.
workers = int(os.environ.get("GUNICORN_WORKERS", "3"))

# Worker class: "sync" is correct for a standard Flask app doing blocking I/O to Postgres.
worker_class = os.environ.get("GUNICORN_WORKER_CLASS", "sync")

# ── Timeouts ──────────────────────────────────────────────────────────────────
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "30"))
graceful_timeout = int(os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", "30"))

# ── Logging ───────────────────────────────────────────────────────────────────
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOGLEVEL", "info")

# ── Worker recycling ──────────────────────────────────────────────────────────
max_requests = int(os.environ.get("GUNICORN_MAX_REQUESTS", "1000"))
max_requests_jitter = int(os.environ.get("GUNICORN_MAX_REQUESTS_JITTER", "50"))

# ── App preloading ────────────────────────────────────────────────────────────
preload_app = os.environ.get("GUNICORN_PRELOAD", "true").lower() in (
    "1", "true", "yes", "on",
)
