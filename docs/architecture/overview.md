# MZADAK Architecture Overview

## Services

| Service      | Stack          | Port | Description                    |
|-------------|----------------|------|--------------------------------|
| backend     | FastAPI        | 8000 | Core API, auth, auction logic  |
| ai-service  | FastAPI + GPU  | 8001 | Image recognition, pricing ML  |
| web         | Next.js        | 3000 | Web frontend (SSR)             |
| mobile      | Flutter        | -    | iOS & Android app              |

## Infrastructure

- **Database**: PostgreSQL 16
- **Cache/Queue**: Redis 7
- **Cloud**: AWS (me-south-1)
- **IaC**: Terraform
- **Containers**: Docker + ECS Fargate
