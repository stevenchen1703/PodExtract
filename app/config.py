from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "PodExtract"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"

    work_dir: str = "/tmp/podextract"
    sqlite_path: str = "/tmp/podextract/podextract.db"

    redis_url: str = "redis://redis:6379/0"
    redis_queue_key: str = "podextract:jobs"

    # Source + dedupe
    dedupe_window_hours: int = 24
    max_rss_items_scan: int = 20

    # Retries
    stage_retry_extract: int = 3
    stage_retry_stt: int = 2
    stage_retry_publish: int = 2
    stage_retry_base_delay_seconds: float = 1.2

    # STT
    stt_primary_provider: str = "minimax"
    stt_fallback_provider: str = "elevenlabs"

    minimax_api_key: str = ""
    minimax_group_id: str = ""
    minimax_stt_url: str = "https://api.minimaxi.chat/v1/audio/transcriptions"
    minimax_stt_model: str = "speech-02-hd"

    elevenlabs_api_key: str = ""
    elevenlabs_model_id: str = "scribe_v1"

    # LLM analysis
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4.1-mini"

    openclaw_base_url: str = ""
    openclaw_api_key: str = ""

    kb_search_url: str = ""
    kb_search_api_key: str = ""

    # Feishu
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_verification_token: str = ""
    feishu_bitable_app_token: str = ""
    feishu_bitable_table_id: str = ""

    @field_validator("stt_primary_provider", "stt_fallback_provider")
    @classmethod
    def _normalize_provider(cls, value: str) -> str:
        return value.strip().lower()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
