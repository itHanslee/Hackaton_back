from functools import lru_cache

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="MediNote Backend", alias="APP_NAME")
    debug: bool = Field(default=False, alias="DEBUG")
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8000, alias="PORT")
    cors_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        alias="CORS_ORIGINS",
    )

    database_url: str = Field(
        default="sqlite:///./medinote.db",
        alias="DATABASE_URL",
    )

    api_timeout_sec: float = Field(default=90.0, alias="API_TIMEOUT_SEC")
    rate_limit_per_minute: int = Field(default=60, alias="RATE_LIMIT_PER_MINUTE")

    mock_ai: bool = Field(default=False, alias="MOCK_AI")

    google_api_key: str = Field(default="", alias="GOOGLE_API_KEY")
    gemini_model: str = Field(default="gemini-2.0-flash", alias="GEMINI_MODEL")

    azure_api_key: str = Field(default="", alias="AZURE_API_KEY")
    azure_openai_endpoint: str = Field(
        default="https://scia.cognitiveservices.azure.com/",
        alias="AZURE_OPENAI_ENDPOINT",
    )
    azure_openai_deployment: str = Field(
        default="gpt-5.3-chat",
        alias="AZURE_OPENAI_DEPLOYMENT",
    )
    azure_openai_api_version: str = Field(
        default="2024-12-01-preview",
        alias="AZURE_OPENAI_API_VERSION",
    )

    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    groq_stt_model: str = Field(default="whisper-large-v3-turbo", alias="GROQ_STT_MODEL")

    jwt_secret: str = Field(default="change-me-in-production", alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_expire_minutes: int = Field(default=480, alias="JWT_EXPIRE_MINUTES")
    auth_disabled: bool = Field(default=False, alias="AUTH_DISABLED")

    smtp_host: str = Field(
        default="smtp.gmail.com",
        validation_alias=AliasChoices("SMTP_HOST", "SMTP_SERVER"),
    )
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_user: str = Field(
        default="",
        validation_alias=AliasChoices("SMTP_USER", "EMAIL_USER"),
    )
    smtp_password: str = Field(
        default="",
        validation_alias=AliasChoices("SMTP_PASSWORD", "EMAIL_PASSWORD"),
    )
    smtp_from: str = Field(default="", alias="SMTP_FROM")
    smtp_use_tls: bool = Field(default=True, alias="SMTP_USE_TLS")
    smtp_enabled: bool = Field(default=False, alias="SMTP_ENABLED")

    max_audio_mb: int = Field(default=10, alias="MAX_AUDIO_MB")
    max_ws_chunks: int = Field(default=500, alias="MAX_WS_CHUNKS")
    ws_transcribe_on_interval: bool = Field(default=False, alias="WS_TRANSCRIBE_ON_INTERVAL")
    ws_transcribe_interval_sec: float = Field(default=2.0, alias="WS_TRANSCRIBE_INTERVAL_SEC")

    pdf_output_dir: str = Field(default="pdfs", alias="PDF_OUTPUT_DIR")
    audio_output_dir: str = Field(default="audio", alias="AUDIO_OUTPUT_DIR")
    signatures_output_dir: str = Field(default="signatures", alias="SIGNATURES_OUTPUT_DIR")
    logos_output_dir: str = Field(default="logos", alias="LOGOS_OUTPUT_DIR")
    max_image_mb: int = Field(default=2, alias="MAX_IMAGE_MB")
    max_signature_mb: int = Field(default=1, alias="MAX_SIGNATURE_MB")
    seed_on_startup: bool = Field(default=True, alias="SEED_ON_STARTUP")

    @model_validator(mode="after")
    def _default_smtp_from(self) -> "Settings":
        if not self.smtp_from.strip() and self.smtp_user.strip():
            object.__setattr__(self, "smtp_from", self.smtp_user.strip())
        elif not self.smtp_from.strip():
            object.__setattr__(self, "smtp_from", "medinote@example.com")
        return self

    @field_validator("mock_ai", mode="before")
    @classmethod
    def parse_mock_ai(cls, value: object) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @field_validator("smtp_password", mode="before")
    @classmethod
    def _normalize_smtp_password(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).replace(" ", "")

    @field_validator("auth_disabled", "smtp_enabled", "smtp_use_tls", mode="before")
    @classmethod
    def parse_bool_flags(cls, value: object) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
