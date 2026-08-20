FROM python:3.12-slim
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY packages/contracts /srv/packages/contracts
RUN pip install -e /srv/packages/contracts
COPY services/core/pyproject.toml /srv/services/core/
COPY services/core/marsad_core /srv/services/core/marsad_core
RUN pip install fastapi "uvicorn[standard]" pydantic pydantic-settings httpx sqlalchemy aiosqlite openpyxl
WORKDIR /srv/services/core
EXPOSE 8000
CMD ["uvicorn", "marsad_core.main:app", "--host", "0.0.0.0", "--port", "8000"]
