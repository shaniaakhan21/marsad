.PHONY: install test test-network run down demo lint
install:
	pip install -e packages/contracts
	pip install fastapi "uvicorn[standard]" pydantic pydantic-settings httpx sqlalchemy aiosqlite openpyxl pytest ruff
test:
	python -m pytest tests/ -v
test-network:
	python -m pytest tests/ -v -m network
lint:
	ruff check packages services tests
run:
	docker compose up --build
down:
	docker compose down -v
demo:
	python scripts/seed_demo.py
