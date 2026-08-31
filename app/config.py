from functools import lru_cache

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    log_level: str = "INFO"
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    embedding_model: str = "text-embedding-3-small"
    pinecone_api_key: str = ""
    pinecone_index: str = "enterprise-knowledge"
    pinecone_namespace: str = "commercial-bank"
    retrieval_top_k: int = 6
    max_query_length: int = 2000
    memory_max_turns: int = 12
    memory_db_path: str = "data/runtime/conversations.db"
    rate_limit_capacity: int = 20
    rate_limit_refill_per_second: float = 0.2
    mcp_url: str = "http://localhost:8010"
    mcp_bind_host: str = "127.0.0.1"
    mcp_shared_secret: SecretStr = SecretStr("change-me-in-production")
    allowed_origins: str = "http://localhost:8501"
    allowed_hosts: str = "localhost,127.0.0.1,testserver,api"
    max_request_bytes: int = 16_384
    viewer_password: SecretStr = SecretStr("viewer123")
    analyst_password: SecretStr = SecretStr("analyst123")
    admin_password: SecretStr = SecretStr("admin123")

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.allowed_origins.split(",") if item.strip()]

    @property
    def trusted_hosts(self) -> list[str]:
        return [item.strip() for item in self.allowed_hosts.split(",") if item.strip()]

    @model_validator(mode="after")
    def reject_insecure_production_defaults(self) -> "Settings":
        if self.app_env != "production":
            return self
        forbidden = {
            "mcp_shared_secret": {"change-me-in-production", "replace-with-a-long-random-value"},
            "viewer_password": {"viewer123", "replace-viewer-password"},
            "analyst_password": {"analyst123", "replace-analyst-password"},
            "admin_password": {"admin123", "replace-admin-password"},
        }
        insecure = [
            name
            for name, weak_values in forbidden.items()
            if getattr(self, name).get_secret_value() in weak_values
        ]
        if insecure:
            raise ValueError(f"insecure production defaults: {', '.join(insecure)}")
        return self

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
