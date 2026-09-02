FROM python:3.12-slim
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY packages/contracts /srv/packages/contracts
RUN pip install -e /srv/packages/contracts
COPY services/connector/pyproject.toml /srv/services/connector/
COPY services/connector/marsad_connector /srv/services/connector/marsad_connector
COPY services/connector/alembic.ini /srv/services/connector/
COPY services/connector/alembic /srv/services/connector/alembic
# camel-tools is deliberately absent. It declares torch and transformers as hard
# dependencies, and torch's Linux wheel pulls ~30 NVIDIA CUDA packages with it — 3.29GB
# inside an institution's perimeter to obtain four character maps. Those maps are vendored in lang/arabic.py and checked against
# the real camel-tools, codepoint by codepoint, by tests/test_vendored_normalisation.py.
RUN pip install fastapi "uvicorn[standard]" pydantic pydantic-settings httpx sqlalchemy \
    "psycopg[binary]" alembic
WORKDIR /srv/services/connector
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn marsad_connector.main:app --host 0.0.0.0 --port 8000"]
