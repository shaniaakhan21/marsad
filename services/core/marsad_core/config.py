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


@lru_cache
def settings() -> Settings:
    return Settings()
