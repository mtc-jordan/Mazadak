"""
Application settings — single source of truth for all configuration.

Reads from environment variables / .env file.  Every service-level
constant referenced in the SDD is exposed here so that no magic
strings leak into business logic.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── General ──────────────────────────────────────────────────
    APP_NAME: str = "MZADAK"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"  # development | staging | production

    # ── API ──────────────────────────────────────────────────────
    API_V1_PREFIX: str = "/api/v1"
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]

    # ── PostgreSQL (async) ───────────────────────────────────────
    DATABASE_URL: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/mzadak"
    )
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_ECHO: bool = False

    # ── Redis ────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_MAX_CONNECTIONS: int = 50

    # ── Celery ───────────────────────────────────────────────────
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # ── JWT / Auth (RS256) ───────────────────────────────────────
    JWT_PRIVATE_KEY_PATH: str = "keys/private.pem"
    JWT_PUBLIC_KEY_PATH: str = "keys/public.pem"
    JWT_ALGORITHM: str = "RS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    OTP_EXPIRE_SECONDS: int = 300          # 5 minutes
    OTP_MAX_REQUESTS_PER_HOUR: int = 5     # rate limit per phone
    OTP_MAX_VERIFY_ATTEMPTS: int = 3       # wrong OTPs before lockout
    OTP_LOCKOUT_SECONDS: int = 900         # 15-minute lockout

    # ── SMS providers ───────────────────────────────────────────
    SMS_PROVIDER: str = "twilio"           # twilio | sns | mock
    AWS_SNS_REGION: str = "me-south-1"

    # ── KYC (FR-AUTH-005) ───────────────────────────────────────
    KYC_AUTO_APPROVE_THRESHOLD: float = 85.0
    KYC_MANUAL_REVIEW_THRESHOLD: float = 70.0
    KYC_MAX_ATTEMPTS: int = 2              # per user lifetime
    KYC_PRESIGNED_URL_EXPIRY: int = 300    # 5 min for upload
    KYC_REVIEWER_URL_EXPIRY: int = 300     # 5 min for reviewer access

    # ── Listings (FR-LIST-001 → FR-LIST-013) ──────────────────────
    LISTING_MAX_ACTIVE_FREE: int = 5           # Free-tier cap
    LISTING_MIN_DURATION_HOURS: int = 1
    LISTING_MAX_DURATION_DAYS: int = 7
    LISTING_MODERATION_THRESHOLD: float = 70.0 # AI score > 70 → queue
    LISTING_PHASH_THRESHOLD: int = 92          # ≥ 92% similarity → flag
    LISTING_PRESIGNED_URL_EXPIRY: int = 300    # 5 min upload window
    LISTING_THUMBNAIL_SIZES: list[int] = [100, 400, 800]

    # ── Checkout.com (Payments) ──────────────────────────────────
    CHECKOUT_SECRET_KEY: str = ""
    CHECKOUT_PUBLIC_KEY: str = ""
    CHECKOUT_WEBHOOK_SECRET: str = ""

    # ── AWS ──────────────────────────────────────────────────────
    AWS_REGION: str = "me-south-1"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    S3_BUCKET_MEDIA: str = "mzadak-media"
    S3_BUCKET_KYC: str = "mzadak-kyc"

    # ── Meilisearch ──────────────────────────────────────────────
    MEILISEARCH_URL: str = "http://localhost:7700"
    MEILISEARCH_API_KEY: str = ""

    # ── ClickHouse (analytics) ───────────────────────────────────
    CLICKHOUSE_HOST: str = "localhost"
    CLICKHOUSE_PORT: int = 8123
    CLICKHOUSE_DATABASE: str = "mzadak_analytics"

    # ── Snap-to-List (FR-LIST-002, PM-04) ──────────────────────────
    SNAP_TO_LIST_TIMEOUT: float = 8.0          # P90 budget in seconds
    SNAP_TO_LIST_CLIP_MIN_CONFIDENCE: float = 40.0  # below → "Other"
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o"

    # ── Price Oracle (FR-AI-001) ─────────────────────────────────
    PRICE_ORACLE_CACHE_TTL: int = 3600         # 1 hour Redis cache
    PRICE_ORACLE_LOOKBACK_DAYS: int = 90       # comparable window
    PRICE_ORACLE_MIN_COMPARABLES: int = 3      # below → confidence=none
    PRICE_ORACLE_MODEL_PATH: str = "models/price_oracle.joblib"

    # ── Notifications ────────────────────────────────────────────
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_PHONE_NUMBER: str = ""
    FIREBASE_CREDENTIALS_PATH: str = ""
    WHATSAPP_ACCESS_TOKEN: str = ""
    WHATSAPP_PHONE_NUMBER_ID: str = ""
    WHATSAPP_RATE_LIMIT_PER_DAY: int = 5  # non-critical per user

    # ── Rate limits ──────────────────────────────────────────────
    RATE_LIMIT_AUTH: int = 1000            # req/min authenticated
    RATE_LIMIT_UNAUTH: int = 100           # req/min unauthenticated
    RATE_LIMIT_BID_PER_MINUTE: int = 10    # bids/user/auction/min

    # ── Auction defaults ─────────────────────────────────────────
    ANTI_SNIPE_WINDOW_SECONDS: int = 120   # bid in last 2 min extends
    ANTI_SNIPE_EXTENSION_SECONDS: int = 120
    MAX_ANTI_SNIPE_EXTENSIONS: int = 5
    DEFAULT_MIN_INCREMENT: float = Field(default=25.0)  # JOD

    # ── Escrow deadlines ─────────────────────────────────────────
    PAYMENT_DEADLINE_HOURS: int = 24
    SHIPPING_DEADLINE_HOURS: int = 48
    INSPECTION_DEADLINE_HOURS: int = 48
    EVIDENCE_DEADLINE_HOURS: int = 24


settings = Settings()
