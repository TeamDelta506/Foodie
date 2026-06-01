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
