from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DEBUG: bool = False
    GPU_ENABLED: bool = True
    MODEL_CACHE_DIR: str = "/app/model_cache"
    REDIS_URL: str = "redis://localhost:6379/1"
    BACKEND_URL: str = "http://localhost:8000"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
