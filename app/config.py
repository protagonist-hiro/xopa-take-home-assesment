from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import List


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://calluser:callpass@postgres:5432/calldb"

    # Redis
    REDIS_URL: str = "redis://redis:6379"

    # MinIO / S3
    S3_ENDPOINT_URL: str = "http://minio:9000"
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    S3_BUCKET: str = "recordings"
    S3_REGION: str = "us-east-1"

    # Recording storage backend: "s3" or "local"
    STORAGE_BACKEND: str = "s3"
    LOCAL_RECORDINGS_DIR: str = "./data/recordings"
    PUBLIC_BASE_URL: str = "http://localhost:8000"

    # Rate limits
    MAX_CONCURRENT_CALLS_PER_KEY: int = 5
    MAX_CPS_PER_KEY: int = 2
    CPS_WINDOW_SECONDS: int = 1

    # Comma-separated list of valid API keys
    VALID_API_KEYS: str = "test-key-1,test-key-2,demo-key"

    # Server
    SERVICE_PORT: int = 8000

    # CORS (comma-separated origins, e.g. https://app.example.com,https://admin.example.com)
    CORS_ALLOW_ORIGINS: str = "*"

    # Debug mode – serves /debug UI behind ADMIN_KEY when true
    DEBUG: bool = False
    ADMIN_KEY: str = ""

    model_config = {"env_file": ".env"}


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_valid_api_keys() -> List[str]:
    return [k.strip() for k in get_settings().VALID_API_KEYS.split(",")]


def get_cors_allow_origins() -> List[str]:
    raw = get_settings().CORS_ALLOW_ORIGINS.strip()
    if not raw:
        return []
    if raw == "*":
        return ["*"]
    return [origin.strip() for origin in raw.split(",") if origin.strip()]
