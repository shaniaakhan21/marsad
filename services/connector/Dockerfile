FROM python:3.12-slim
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY packages/contracts /srv/packages/contracts
RUN pip install -e /srv/packages/contracts
COPY services/connector/pyproject.toml /srv/services/connector/
COPY services/connector/marsad_connector /srv/services/connector/marsad_connector
COPY services/connector/alembic.ini /srv/services/connector/
COPY services/connector/alembic /srv/services/connector/alembic
RUN pip install fastapi "uvicorn[standard]" pydantic pydantic-settings httpx sqlalchemy \
    "psycopg[binary]" alembic camel-tools
WORKDIR /srv/services/connector
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn marsad_connector.main:app --host 0.0.0.0 --port 8000"]
