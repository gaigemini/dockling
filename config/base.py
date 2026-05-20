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
    UPLOAD_DIR: str = "uploads"
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

    # Docling pipeline options
    ENABLE_TABLE_STRUCTURE: bool = True
    ENABLE_CELL_MATCHING: bool = True

    # CORS
    CORS_ORIGINS: str = "*"

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