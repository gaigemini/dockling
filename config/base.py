from pydantic_settings import BaseSettings
from typing import List, Optional

class BaseConfig(BaseSettings):
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
    
    # Security
    SECRET_KEY: str = "default-secret-key-change-in-production"
    DISABLE_AUTH: bool = False
    
    class Config:
        env_file_encoding = 'utf-8'
        extra = "allow"
        