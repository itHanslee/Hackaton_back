from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "MediNote Backend"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    api_timeout_sec: int = 30
    rate_limit_per_minute: int = 60

    mock_ai: bool = True
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    stt_provider: str = "grok"
    stt_model: str = "grok-4-20-non-reasoning"
    azure_ai_stt_endpoint: str = "https://scia.services.ai.azure.com/openai/v1/"
    azure_api_key: str = ""

    database_url: str = "sqlite:///./medinote.db"


    max_audio_mb: int = 10
    max_ws_chunks: int = 500
    ws_transcribe_on_interval: bool = False
    ws_transcribe_interval_sec: float = 2.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
