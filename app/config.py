from functools import lru_cache

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
    rate_limit_capacity: int = 20
    rate_limit_refill_per_second: float = 0.2
    mcp_url: str = "http://localhost:8010"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
