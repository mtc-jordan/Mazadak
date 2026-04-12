# ── CPU-only base (default for dev / CI) ─────────────────────────
FROM python:3.12-slim AS base-cpu

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONPATH=/app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY . .

# ── GPU base (production with NVIDIA runtime) ────────────────────
FROM nvidia/cuda:12.3.2-runtime-ubuntu22.04 AS base-gpu

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip3 install --no-cache-dir --upgrade pip setuptools

WORKDIR /app
ENV PYTHONPATH=/app

COPY pyproject.toml .
RUN pip3 install --no-cache-dir .

COPY . .

# ── Development (CPU) ────────────────────────────────────────────
FROM base-cpu AS development
RUN pip install --no-cache-dir ".[dev]"
EXPOSE 8001
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--reload"]

# ── Production CPU ───────────────────────────────────────────────
FROM base-cpu AS production
EXPOSE 8001
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "2"]

# ── Production GPU ───────────────────────────────────────────────
FROM base-gpu AS production-gpu
EXPOSE 8001
CMD ["python3", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "2"]
