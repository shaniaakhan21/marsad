# One key custodian. Runs alone on the custodian network: it has no route to a core,
# no database, and sees only blinded group elements.
FROM python:3.12-slim
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
# libsodium provides every curve operation. See packages/oprf/marsad_oprf/group.py.
RUN apt-get update && apt-get install -y --no-install-recommends libsodium23 \
    && rm -rf /var/lib/apt/lists/*
COPY packages/contracts /srv/packages/contracts
COPY packages/oprf /srv/packages/oprf
RUN pip install -e /srv/packages/contracts -e /srv/packages/oprf
COPY services/evaluator/marsad_evaluator /srv/services/evaluator/marsad_evaluator
RUN pip install fastapi "uvicorn[standard]" pydantic pydantic-settings
WORKDIR /srv/services/evaluator
EXPOSE 8000
CMD ["uvicorn", "marsad_evaluator.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
