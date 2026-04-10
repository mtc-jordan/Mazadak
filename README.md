# MZADAK

Online auction platform - monorepo.

## Structure

```
├── backend/        FastAPI - Core API service
├── mobile/         Flutter - iOS & Android app
├── web/            Next.js - Web frontend
├── ai-service/     FastAPI + GPU - ML/AI service
├── infra/          Terraform & Docker Compose
└── docs/           Architecture & API docs
```

## Quick Start

```bash
# Start all services (Docker)
make dev

# Run tests across all services
make test

# Run database migrations
make migrate

# Seed the database
make seed
```

## Prerequisites

- Docker & Docker Compose
- Python 3.11+
- Node.js 20+
- Flutter 3.19+
- Terraform 1.7+ (for infra)

## Services

| Service     | Port | Stack         |
|------------|------|---------------|
| backend    | 8000 | FastAPI       |
| ai-service | 8001 | FastAPI + GPU |
| web        | 3000 | Next.js       |
| postgres   | 5432 | PostgreSQL 16 |
| redis      | 6379 | Redis 7       |
