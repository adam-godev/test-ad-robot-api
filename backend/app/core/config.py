from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@postgres:5432/keitaro_test",
        alias="DATABASE_URL",
    )
    frontend_url: str = Field(default="http://localhost:3000", alias="FRONTEND_URL")

    keitaro_base_url: str = Field(default="https://demo.keitaro.io", alias="KEITARO_BASE_URL")
    keitaro_api_key: str = Field(default="replace-me", alias="KEITARO_API_KEY")
    keitaro_campaign_domain_url: str | None = Field(default=None, alias="KEITARO_CAMPAIGN_DOMAIN_URL")
    keitaro_domain_id: int | None = Field(default=None, alias="KEITARO_DOMAIN_ID")
    keitaro_group_id: int | None = Field(default=None, alias="KEITARO_GROUP_ID")
    keitaro_traffic_source_id: int | None = Field(default=None, alias="KEITARO_TRAFFIC_SOURCE_ID")

    @field_validator("frontend_url", "keitaro_base_url", "keitaro_campaign_domain_url")
    @classmethod
    def normalize_urls(cls, value: str | None) -> str | None:
        return value.rstrip("/") if value else value


@lru_cache
def get_settings() -> Settings:
    return Settings()
