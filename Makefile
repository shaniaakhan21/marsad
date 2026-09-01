.PHONY: install test test-network test-e2e run down demo lint
install:
	pip install -e packages/contracts
	pip install fastapi "uvicorn[standard]" pydantic pydantic-settings httpx sqlalchemy aiosqlite openpyxl camel-tools pytest ruff
	cd apps/web && npm install && npx playwright install --with-deps chromium
test:
	python -m pytest tests/ -v
test-network:
	python -m pytest tests/ -v -m network
test-e2e:
	cd apps/web && npm run test:e2e
lint:
	ruff check packages services tests
run:
	docker compose up --build
down:
	docker compose down -v
demo:
	python scripts/seed_demo.py
