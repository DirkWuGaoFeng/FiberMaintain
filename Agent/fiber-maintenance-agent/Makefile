.PHONY: install dev ingest test report up down logs lint

install:
	pip install -r requirements.txt

dev:
	uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload

ingest:
	python -m src.rag.ingest --rebuild

test:
	pytest tests/ -v --html=tests/reports/report.html --self-contained-html

report:
	python tests/test_client.py --all --report

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f deerflow