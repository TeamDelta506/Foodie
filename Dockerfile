# Dockerfile — for the Flask app container

FROM python:3.12-slim

WORKDIR /app

# Install Python dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Default command — gunicorn with the canonical config
CMD ["gunicorn", "-c", "gunicorn.conf.py", "yourapp:create_app()"]
