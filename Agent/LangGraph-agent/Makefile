.PHONY: dev test lint docker-build docker-up docker-down clean install start start-all frontend-dev

# Development
install:
	pip install -e ".[dev]"

dev:
	uvicorn src.server:app --host 0.0.0.0 --port 8000 --reload

# Testing
test:
	pytest tests/ -v --cov=src

test-unit:
	pytest tests/unit/ -v

test-integration:
	pytest tests/integration/ -v

# Linting
lint:
	ruff check src/
	ruff format --check src/

format:
	ruff check --fix src/
	ruff format src/

# Docker
docker-build:
	docker compose build

docker-up:
	docker compose up -d

docker-up-dev:
	docker compose --profile dev up -d

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f langgraph-app

# Data management
ingest-kb:
	python -c "from src.rag.ingest import ingest_knowledge_base; ingest_knowledge_base()"

# Cleanup
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf data/checkpoints.db data/memory.db

# One-click start
start:
	uvicorn src.server:app --host 0.0.0.0 --port 8000 --reload

start-all:
	bash start.sh

frontend-dev:
	cd frontend && npm install && npm run dev
