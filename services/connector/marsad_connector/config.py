from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MARSAD_", env_file=".env", extra="ignore")

    institution_name: str = "Demo Institution"
    institution_ref: str = "psd_demo0001"
    sector: str = "BANK"
    size_band: str = "MID"

    #: Regulatory perimeters this institution sits inside — drives A4. A UAE firm
    #: can hold several at once, which is the whole reason A4 exists. Comma
    #: separated in the environment: MARSAD_JURISDICTIONS=ADGM_FSRA,CBUAE
    jurisdictions_raw: str = "CBUAE,CMA"

    @property
    def jurisdictions(self) -> list[str]:
        return [j.strip().upper() for j in self.jurisdictions_raw.split(",") if j.strip()]

    core_url: str = "http://core:8000"
    token_key: str = ""
    tokeniser: str = "hmac"          # hmac | oprf
    database_url: str = "sqlite+aiosqlite:///./connector.db"
    llm_provider: str = "stub"       # stub | openai_compatible


@lru_cache
def settings() -> Settings:
    return Settings()
