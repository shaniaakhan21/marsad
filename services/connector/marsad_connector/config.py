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

    #: Mutual TLS to the core, for a connector on separate hardware reaching it across
    #: the public internet. A client certificate rather than a bearer token: a token in
    #: an environment variable is readable by anyone with the image or the logs, while
    #: this key never leaves the institution. Empty means plain HTTP to a core on the
    #: same host, which is only appropriate when the network already isolates them.
    core_client_cert: str = ""
    core_client_key: str = ""
    core_ca_bundle: str = ""
    token_key: str = ""
    tokeniser: str = "hmac"          # hmac | oprf

    #: The key epoch and the values this connector pins for it, from
    #: scripts/oprf_keygen.py. Pinned, not fetched: an evaluator that supplied its own
    #: public key could prove anything. `oprf_custodians` is a JSON list of
    #: {"index", "url", "public_share"}.
    oprf_epoch: int = 1
    oprf_threshold: int = 2
    oprf_group_key: str = ""
    oprf_custodians: str = "[]"
    #: Recorded in the tokeniser scheme: "software" until shares move to hardware.
    oprf_custody_label: str = "software"
    #: The institution's own store. Holds plaintext, and the core has no route to
    #: it — separate instance, separate schema, separate MetaData. See db/base.py.
    database_url: str = "sqlite:///./connector.db"

    #: "sql" or "memory". The in-memory backend keeps the test suite fast.
    store: str = "sql"
    auto_create_schema: bool = True

    #: Days before narrative, analyst notes, the attacker's email body and every
    #: extraction provenance row expire. Provenance quotes the narrative verbatim, so
    #: it expires with it and never after it. See db/retention.py.
    retention_days: int = 90

    #: How often the purge runs, in seconds. A policy nobody executes is a sentence in a
    #: document. 0 turns the schedule off; only tests should want that.
    retention_purge_interval_seconds: int = 3600

    #: Browser origins allowed to call this connector, comma separated. Never `*`: this
    #: process serves plaintext incidents, and a wildcard would let any page an analyst
    #: visits read them.
    cors_origins: str = "http://localhost:3000"

    #: Bearer token for the analyst console. Empty leaves the API open, for a connector
    #: reachable only on the analyst's own machine; /health reports which it is.
    console_token: str = ""
    llm_provider: str = "stub"       # stub | openai_compatible

    #: OpenAI-compatible root (the URL ending in /v1) of a model served inside the
    #: institution's perimeter — Ollama or vLLM. Checked at construction, not at
    #: request time; see llm/sovereignty.py.
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""

    #: Ceiling on model calls per rolling day. 0 disables the model path entirely.
    #: A public demo without this is someone else's free compute. When it is spent,
    #: extraction degrades to the deterministic extractor rather than failing — see
    #: llm/budget.py. Unset means no ceiling, which is right for a private deployment
    #: and wrong for a public one.
    llm_daily_call_budget: int = 0

    #: Refuse to build an LLM provider whose endpoint is reachable on the public
    #: internet. Default on. Turning it off means accepting that plaintext incident
    #: narrative, analyst notes and PII may leave the institution.
    sovereign_mode: bool = True


@lru_cache
def settings() -> Settings:
    return Settings()
