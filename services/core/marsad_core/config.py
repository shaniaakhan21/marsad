from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MARSAD_CORE_", env_file=".env", extra="ignore")

    #: The store of record. Postgres in deployment; SQLite locally. NEVER an edge
    #: database — the core has no business being able to open one. See db/base.py.
    database_url: str = "sqlite:///./core.db"

    #: "sql" or "memory". The in-memory backend exists so the test suite stays fast
    #: and so nothing in the correlation algorithm can start assuming a database.
    store: str = "sql"

    #: Create the schema on boot instead of requiring a migration run. Convenient
    #: locally, wrong in deployment — Alembic owns the schema there (`make migrate`).
    auto_create_schema: bool = True
    similarity_engine: str = "jaccard"     # jaccard | weighted | enclave | smpc
    similarity_threshold: float = 0.60
    k_anonymity: int = 3

    #: Browser origins allowed to call this API, comma separated. Never `*`.
    cors_origins: str = "http://localhost:3000"

    #: Require a verified client certificate on POST /v1/submissions, passed by the proxy
    #: in X-Client-Cert-Subject. Off only for the single-host demo, where Docker networks
    #: do the isolating and there are no certificates. On in every real deployment.
    require_client_identity: bool = False

    #: Pseudonyms allowed to submit, comma separated. Empty means any certificate the
    #: federation CA signed; a real federation lists its members.
    registered_institutions_raw: str = ""

    #: `role:token,role:token` for console reads; roles are operator and regulator.
    #: Empty leaves the read API open, which /health reports. See security.py.
    console_tokens: str = ""

    #: Enrolled providers, as JSON: {token: {name, service, market_activity_share,
    #: owner_ref}}. Published by the operator from each provider's own enrolment, so a
    #: provider's name never crosses from a firm. See services/providers.py.
    provider_directory: str = "{}"

    #: Seconds between anchoring runs. 0 turns the background loop off.
    anchor_interval_seconds: int = 300

    #: "local" (a hash chain in this database, labelled reduced fidelity) or "besu".
    ledger_backend: str = "local"
    besu_rpc_url: str = ""
    besu_contract_address: str = ""
    besu_private_key: str = ""
    besu_artifact_path: str = "/srv/contracts/ReceiptAnchor.json"

    @property
    def registered_institutions(self) -> frozenset[str]:
        return frozenset(
            r.strip() for r in self.registered_institutions_raw.split(",") if r.strip()
        )


@lru_cache
def settings() -> Settings:
    return Settings()
