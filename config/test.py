from .base import BaseConfig

class TestConfig(BaseConfig):
    DEBUG: bool = True
    LOG_LEVEL: str = "CRITICAL"
    TEMP_DIR: str = "test_uploads/tmp"
    SUPPORTED_FORMATS: str = "application/pdf,text/plain"
    DEFAULT_OCR_LANGS: str = "id"
    MAX_TOKENS: int = 512
    DEFAULT_CHUNK_TYPE: str = "hybrid"
    SECRET_KEY: str = "test-secret-key"
    DISABLE_AUTH: bool = True