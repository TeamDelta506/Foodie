FROM python:3.12-slim

WORKDIR /app

# Install Python dependencies first (cached layer — only rebuilds when requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# gunicorn creates the unix socket inside the shared volume mounted at /tmp.
# No port is exposed — nginx on the same docker network reaches gunicorn via the socket.
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app:app"]
