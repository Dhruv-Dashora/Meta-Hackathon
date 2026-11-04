"""App configuration — env vars only."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"
    database_url: str = "sqlite:///./storage/sentinel.db"
    storage_dir: str = "./storage"
    log_level: str = "INFO"

    # Meta Muse Spark (backend only — never log or return the key).
    # 60s matches the SAM image timeout: the three-category prompt
    # elicits multi-finding output and uploads run to ~7MB base64.
    model_api_key: str = ""
    muse_spark_base_url: str = "https://api.meta.ai/v1"
    muse_spark_model: str = "muse-spark-1.3"
    muse_spark_timeout_s: float = Field(default=60.0, gt=0)

    # Meta SAM 3.1 segmentation (same MODEL_API_KEY as Muse Spark).
    sam31_base_url: str = "https://api.meta.ai/v1"
    sam31_model: str = "sam-3.1"
    sam31_timeout_s: float = Field(default=60.0, gt=0)

    # Upload guardrails.
    max_image_bytes: int = Field(default=5 * 1024 * 1024, gt=0)
    # Decoded-raster cap: a small compressed file must not expand into
    # an unbounded bitmap during dimension checks.
    max_image_pixels: int = Field(default=50_000_000, gt=0)

    # Unified analyze-and-segment workflow: total time budget in seconds
    # covering the Muse Spark call plus all SAM 3.1 calls.
    unified_workflow_budget_s: float = Field(default=90.0, gt=0)

    # Operator-supplied GeoJSON guardrail.
    max_geojson_bytes: int = Field(default=512 * 1024, gt=0)

    # Browser-session binding for cached analyses (opaque ids, TTL eviction).
    session_ttl_s: float = Field(default=8 * 3600.0, gt=0)

    # Analysis evidence cache (in-memory MVP): bounded count, TTL, and
    # per-entry serialized size. Entries are server-held objects keyed by
    # an unpredictable reference plus the owning session id.
    analysis_cache_ttl_s: float = Field(default=1800.0, gt=0)
    analysis_cache_max_entries: int = Field(default=100, ge=1)
    analysis_cache_max_entry_bytes: int = Field(default=2 * 1024 * 1024, gt=0)

    # Browser origins allowed to call the API cross-origin (comma
    # separated). Same-origin and dev-proxy setups need no entries here.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
