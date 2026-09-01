.PHONY: install test test-network test-e2e test-boundary test-llm run down demo lint migrate
install:
	pip install -e packages/contracts
	pip install fastapi "uvicorn[standard]" pydantic pydantic-settings httpx sqlalchemy \
	  "psycopg[binary]" alembic openpyxl pytest ruff
	# The oracle for the vendored Arabic normalisation. A test dependency only — it is
	# never installed in the connector image. See services/connector/pyproject.toml.
	pip install "camel-tools>=1.5"
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
# The model path against a live endpoint. Needs Ollama running with the model pulled;
# see docs/model-path-results.md for what running it found.
test-llm:
	python -m pytest tests/test_llm_live.py -v -m llm

lint:
	ruff check packages services tests
# Both databases, empty to current, in one command. Two separate migration trees on
# purpose — one history spanning both sides would invite pointing them at one database.
migrate:
	cd services/core && alembic upgrade head
	cd services/connector && alembic upgrade head

run:
	docker compose up --build
down:
	docker compose down -v
demo:
	python scripts/seed_demo.py
