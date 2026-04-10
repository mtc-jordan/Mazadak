.PHONY: dev dev-down dev-logs dev-reset migrate seed test lint worker beat keys

# ── Development ──────────────────────────────────────────────────

dev: keys
	docker compose up -d --wait
	docker compose exec api alembic upgrade head
	docker compose exec api python -m scripts.seed
	@echo ""
	@echo "  API:        http://localhost:8000"
	@echo "  Docs:       http://localhost:8000/docs"
	@echo "  Flower:     http://localhost:5555"
	@echo "  Meilisearch: http://localhost:7700"
	@echo "  ClickHouse: http://localhost:8123"
	@echo ""

dev-down:
	docker compose down

dev-reset:
	docker compose down -v
	$(MAKE) dev

dev-logs:
	docker compose logs -f api worker

# ── Database ─────────────────────────────────────────────────────

migrate:
	docker compose exec api alembic upgrade head

seed:
	docker compose exec api python -m scripts.seed

# ── Testing & Quality ────────────────────────────────────────────

test:
	pytest --cov=app --cov-report=term-missing -q

lint:
	ruff check app/ tests/
	ruff format --check app/ tests/
	mypy app/

# ── Celery (bare-metal, not Docker) ─────────────────────────────

worker:
	celery -A app.core.celery worker --loglevel=info --concurrency=4

beat:
	celery -A app.core.celery beat --loglevel=info

# ── Setup helpers ────────────────────────────────────────────────

keys:
	@if [ ! -f keys/private.pem ]; then \
		mkdir -p keys && \
		openssl genrsa -out keys/private.pem 2048 2>/dev/null && \
		openssl rsa -in keys/private.pem -pubout -out keys/public.pem 2>/dev/null && \
		echo "JWT RS256 keys generated in keys/"; \
	fi
