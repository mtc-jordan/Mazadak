FROM python:3.12-slim

WORKDIR /app

# System deps for asyncpg, Pillow, and healthcheck curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (layer caching)
COPY pyproject.toml .
RUN pip install --no-cache-dir "."

# Copy application code
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
