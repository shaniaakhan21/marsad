FROM python:3.12-slim
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY packages/contracts /srv/packages/contracts
RUN pip install -e /srv/packages/contracts
COPY services/connector/pyproject.toml /srv/services/connector/
COPY services/connector/marsad_connector /srv/services/connector/marsad_connector
RUN pip install fastapi "uvicorn[standard]" pydantic pydantic-settings httpx sqlalchemy \
    aiosqlite camel-tools
WORKDIR /srv/services/connector
EXPOSE 8000
CMD ["uvicorn", "marsad_connector.main:app", "--host", "0.0.0.0", "--port", "8000"]
