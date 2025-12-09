from .base import BaseConfig

class ProdConfig(BaseConfig):
    DEBUG: bool = False
    LOG_LEVEL: str = "WARNING"
    DISABLE_AUTH: bool = False