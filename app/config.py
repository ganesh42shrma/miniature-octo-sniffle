from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Service settings, read from environment variables prefixed with PARSER_."""

    model_config = SettingsConfigDict(env_prefix="PARSER_", extra="ignore")

    max_file_mb: int = 10
    log_level: str = "INFO"


settings = Settings()
