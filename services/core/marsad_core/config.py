from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MARSAD_CORE_", env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./core.db"
    similarity_engine: str = "jaccard"     # jaccard | weighted | enclave | smpc
    similarity_threshold: float = 0.60
    k_anonymity: int = 3


@lru_cache
def settings() -> Settings:
    return Settings()
