from .base import BaseConfig

class DevConfig(BaseConfig):
    DEBUG: bool = True
    LOG_LEVEL: str = "DEBUG"
    UPLOAD_DIR: str = "uploads"
    SUPPORTED_FORMATS: str = "application/pdf,text/plain,text/markdown,text/csv,text/html,application/json,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.presentationml.presentation,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,image/*,application/xml"
    DEFAULT_OCR_LANGS: str = "id"
    MAX_TOKENS: int = 512
    DEFAULT_CHUNK_TYPE: str = "hybrid"
    SECRET_KEY: str = "dev-secret-key-for-docling-app"
    DISABLE_AUTH: bool = True