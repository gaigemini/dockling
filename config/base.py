"""Base configuration schema for all environments."""

from typing import Optional

from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class BaseConfig(BaseSettings):
    """Base configuration with all environment variable definitions."""

    APP_NAME: str = "Docling Document Processing API"
    APP_ENV: str = "dev"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # Document processing settings
    # Local scratch directory for pending uploads and MinIO downloads.
    # Durable input/result artifacts live in MinIO (see MINIO_* settings below).
    TEMP_DIR: str = "uploads/tmp"
    SUPPORTED_FORMATS: str = "application/pdf,text/plain"
    DEFAULT_OCR_LANGS: str = "id"
    MAX_TOKENS: int = 512
    DEFAULT_CHUNK_TYPE: str = "hybrid"
    MAX_FILE_SIZE: int = 209715200  # 200MB
    MAX_STREAM_SIZE: int = 52428800  # 50MB - threshold for auto stream vs file-based
    UPLOAD_CHUNK_SIZE: int = 8192  # 8KB chunks for file reading

    # Performance / Threading
    THREAD_POOL_SIZE: int = 4
    CONVERTER_NUM_THREADS: int = 6
    MAX_CONCURRENT_CONVERSIONS: int = 4  # endpoint limiter, 429 when saturated

    # Docling pipeline options
    ENABLE_TABLE_STRUCTURE: bool = True
    ENABLE_CELL_MATCHING: bool = True
    TABLE_STRUCTURE_MODE: str = "accurate"  # "accurate" or "fast"

    # CORS
    CORS_ORIGINS: str = "*"

    # Redis settings
    REDIS_URL: str = "redis://localhost:6379/0"
    TASK_RESULT_TTL: int = 604800  # 7 days - keep aligned with MINIO_RESULT_TTL_DAYS
    TASK_QUEUE_MAX_SIZE: int = 100  # max pending tasks in queue
    TASK_QUEUE_TIMEOUT: int = 43200  # 12h - max seconds a task may wait in the queue
    TASK_PROCESSING_TIMEOUT: int = 5400  # 90m - default max processing time (30m+ docs)
    TASK_PROCESSING_TIMEOUT_MAX: int = 10800  # hard cap for per-request timeout override
    UPLOAD_SESSION_TTL: int = 7200  # 2h - resumable upload session TTL in Redis
    JANITOR_INTERVAL: int = 60  # watchdog scan interval in seconds
    WORKER_CONCURRENCY: int = 1  # concurrent conversions per worker (GPU-bound)

    # MinIO / object storage settings
    MINIO_ENABLED: bool = False  # False -> local-disk fallback (dev/test)
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "docling"
    MINIO_SECURE: bool = False
    MINIO_REGION: Optional[str] = None
    MINIO_UPLOAD_PREFIX: str = "uploads"  # object key prefix for uploaded inputs
    MINIO_RESULT_PREFIX: str = "results"  # object key prefix for result artifacts
    MINIO_PRESIGN_EXPIRY: int = 3600  # presigned URL lifetime in seconds
    MINIO_DELETE_INPUT_ON_COMPLETE: bool = True  # delete input object after processing
    MINIO_RETENTION_HOURS: int = 24  # input retention when deletion is disabled
    MINIO_RESULT_TTL_DAYS: int = 7  # lifecycle expiry for the results/ prefix

    # Callback / webhook settings
    CALLBACK_TIMEOUT: float = 10.0
    CALLBACK_MAX_RETRIES: int = 3
    CALLBACK_ALLOWED_HOSTS: str = ""  # comma-separated allowlist; empty = any public host

    # Auth settings
    AUTH_INTROSPECT_CACHE_TTL: int = 60  # token introspection cache in seconds

    # Security
    SECRET_KEY: str = "default-secret-key-change-in-production"
    DISABLE_AUTH: bool = False

    # SSO Settings
    SSO_URL: str = "http://127.0.0.1:1877"
    SSO_REALM: str = "GAI"
    SSO_CLIENT_ID: str = "icode"
    SSO_CLIENT_SECRET: Optional[str] = None
    SSO_REDIRECT_URI: str = "http://localhost:1877"

    # JWT Settings
    jwt_secret_key: str = "default-jwt-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expired_in: str = "60"

    model_config = ConfigDict(
        env_file_encoding="utf-8",
        extra="allow",
    )