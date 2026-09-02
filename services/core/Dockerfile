FROM python:3.12-slim
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY packages/contracts /srv/packages/contracts
RUN pip install -e /srv/packages/contracts
COPY services/core/pyproject.toml /srv/services/core/
COPY services/core/marsad_core /srv/services/core/marsad_core
COPY services/core/alembic.ini /srv/services/core/
COPY services/core/alembic /srv/services/core/alembic
RUN pip install fastapi "uvicorn[standard]" pydantic pydantic-settings httpx sqlalchemy \
    "psycopg[binary]" alembic openpyxl
WORKDIR /srv/services/core
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn marsad_core.main:app --host 0.0.0.0 --port 8000"]
