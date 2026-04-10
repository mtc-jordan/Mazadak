.PHONY: dev stop logs test test-backend test-ai test-web migrate migrate-create seed \
       clean shell db-shell redis-shell worker-logs help env keys

COMPOSE = docker compose -f infra/docker/docker-compose.yml
BACKEND = $(COMPOSE) exec backend

# ---------------------------------------------------------------------------
# Development
# ---------------------------------------------------------------------------

dev: env keys ## Start all services in development mode
	$(COMPOSE) up --build -d
	@echo ""
	@echo "  Backend API:   http://localhost:8000/docs"
	@echo "  Meilisearch:   http://localhost:7700"
	@echo "  Flower:        http://localhost:5555"
	@echo "  PostgreSQL:    localhost:5432"
	@echo "  Redis:         localhost:6379"
	@echo ""

stop: ## Stop all services
	$(COMPOSE) down

restart: ## Restart backend + workers (no infra rebuild)
	$(COMPOSE) restart backend celery-worker celery-beat

logs: ## Tail logs for all services
	$(COMPOSE) logs -f

logs-backend: ## Tail backend logs only
	$(COMPOSE) logs -f backend

logs-worker: ## Tail celery worker logs only
	$(COMPOSE) logs -f celery-worker celery-beat

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------

test: test-backend ## Run all tests

test-backend: ## Run backend tests
	$(BACKEND) python -m pytest app/tests -v --tb=short

test-cov: ## Run backend tests with coverage
	$(BACKEND) python -m pytest app/tests -v --cov=app --cov-report=term-missing

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

migrate: ## Run database migrations
	$(BACKEND) alembic upgrade head

migrate-create: ## Create a new migration (usage: make migrate-create MSG="add users table")
	$(BACKEND) alembic revision --autogenerate -m "$(MSG)"

migrate-down: ## Rollback one migration
	$(BACKEND) alembic downgrade -1

seed: ## Seed the database with sample data
	$(BACKEND) python -m app.db.seed

# ---------------------------------------------------------------------------
# Shell access
# ---------------------------------------------------------------------------

shell: ## Open a Python shell inside the backend container
	$(BACKEND) python

db-shell: ## Open psql shell
	$(COMPOSE) exec postgres psql -U postgres -d mzadak

redis-shell: ## Open redis-cli
	$(COMPOSE) exec redis redis-cli

# ---------------------------------------------------------------------------
# Setup helpers
# ---------------------------------------------------------------------------

env: ## Create .env from .env.example if it doesn't exist
	@test -f backend/.env || (cp backend/.env.example backend/.env && echo "Created backend/.env from .env.example")

keys: ## Generate RS256 key pair if missing
	@mkdir -p backend/keys
	@test -f backend/keys/private.pem || \
		(openssl genrsa -out backend/keys/private.pem 2048 2>/dev/null && \
		 openssl rsa -in backend/keys/private.pem -pubout -out backend/keys/public.pem 2>/dev/null && \
		 echo "Generated RS256 key pair in backend/keys/")

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

clean: ## Remove containers, volumes, and build artifacts
	$(COMPOSE) down -v --remove-orphans
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'
