.PHONY: install test test-network test-e2e test-boundary run down demo lint
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
# Proves the edge/core split at the network layer, inside the real containers.
# Brings the stack up, runs the boundary suite, tears it down again.
test-boundary:
	docker compose up -d --build
	python -m pytest tests/test_network_boundary.py -v -m docker; \
	  status=$$?; docker compose down; exit $$status
lint:
	ruff check packages services tests
run:
	docker compose up --build
down:
	docker compose down -v
demo:
	python scripts/seed_demo.py
