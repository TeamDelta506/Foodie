# gunicorn.conf.py — Foodie production Gunicorn config

import os

# Where gunicorn listens. Unix socket for nginx on the same host.
bind = os.environ.get("GUNICORN_BIND", "unix:/tmp/gunicorn.sock")

# Alternative for docker-compose with TCP:
# bind = os.environ.get("GUNICORN_BIND", "0.0.0.0:8000")

# Number of worker processes. Rule of thumb: (2 * CPU cores) + 1.
# Use an env var so you can tune per host without editing the file.
workers = int(os.environ.get("GUNICORN_WORKERS", "3"))

# Worker class. "sync" is the default and right for most apps.
worker_class = os.environ.get("GUNICORN_WORKER_CLASS", "sync")

# Per-worker request timeout. Kills hung workers.
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "30"))

# How long to let in-flight requests finish during a graceful restart.
graceful_timeout = int(os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", "30"))

# Logs to stdout/stderr so Docker/systemd captures them.
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOGLEVEL", "info")

# Restart workers periodically to mitigate any memory leaks.
max_requests = int(os.environ.get("GUNICORN_MAX_REQUESTS", "1000"))
max_requests_jitter = int(os.environ.get("GUNICORN_MAX_REQUESTS_JITTER", "50"))

# Preload the app before forking workers. Faster startup; keep DB connections
# created lazily (SQLAlchemy engines are fine as long as you don't connect at import time).
preload_app = os.environ.get("GUNICORN_PRELOAD", "true").lower() in ("1", "true", "yes", "on")

