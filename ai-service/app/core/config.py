from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DEBUG: bool = False
    GPU_ENABLED: bool = True
    MODEL_CACHE_DIR: str = "/app/model_cache"
    REDIS_URL: str = "redis://localhost:6379/1"
    BACKEND_URL: str = "http://localhost:8000"

    OPENAI_API_KEY: str = ""
    S3_BUCKET: str = "mzadak-uploads"
    AWS_REGION: str = "me-south-1"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    CLICKHOUSE_URL: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
