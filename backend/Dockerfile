FROM python:3.12-slim AS base

WORKDIR /app
ENV PYTHONPATH=/app

# System deps for asyncpg, Pillow, imagehash, and healthcheck curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (layer caching)
COPY pyproject.toml .
RUN pip install --no-cache-dir "."

# Copy application code
COPY . .

# Generate RSA key pair for JWT if not mounted
RUN mkdir -p keys && \
    if [ ! -f keys/private.pem ]; then \
        openssl genrsa -out keys/private.pem 2048 && \
        openssl rsa -in keys/private.pem -pubout -out keys/public.pem; \
    fi

EXPOSE 8000

FROM base AS development
RUN pip install --no-cache-dir ".[dev]"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

FROM base AS production
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
