FROM nvidia/cuda:12.3.2-runtime-ubuntu22.04 AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip3 install --no-cache-dir --upgrade pip setuptools

WORKDIR /app
ENV PYTHONPATH=/app

COPY pyproject.toml .
RUN pip3 install --no-cache-dir .

COPY . .

FROM base AS development
RUN pip3 install --no-cache-dir ".[dev]"
EXPOSE 8001
CMD ["python3", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--reload"]

FROM base AS production
EXPOSE 8001
CMD ["python3", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "2"]
