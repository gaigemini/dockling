import os
import sys
from dotenv import load_dotenv
from .base import BaseConfig
from .dev import DevConfig
from .test import TestConfig
from .prod import ProdConfig

def setup_config():
    """Setup configuration with proper error handling"""
    try:
        # Load ONLY the environment selector
        load_dotenv(".env", override=False)
        APP_ENV = os.getenv("APP_ENV", "dev").lower()
        print(f"🔧 Loading environment: {APP_ENV}", file=sys.stderr)

        # Environment mapping
        env_configs = {
            "dev": DevConfig,
            "test": TestConfig,
            "prod": ProdConfig
        }

        # Get config class for current environment
        ConfigClass = env_configs.get(APP_ENV, DevConfig)

        # Load environment-specific .env file
        env_file = f"env/{APP_ENV}.env"
        
        # Check if env file exists
        if not os.path.exists(env_file):
            print(f"⚠️  Environment file {env_file} not found, using defaults", file=sys.stderr)
            settings_instance = ConfigClass()
        else:
            print(f"📁 Loading config from: {env_file}", file=sys.stderr)
            settings_instance = ConfigClass(_env_file=env_file, _env_file_encoding='utf-8')

        # Critical production safeguard
        if APP_ENV == "prod" and settings_instance.DEBUG:
            raise RuntimeError("DEBUG must be disabled in production!")
            
        print(f"✅ Configuration loaded successfully for {APP_ENV} environment", file=sys.stderr)
        return settings_instance
        
    except Exception as e:
        print(f"❌ Failed to load configuration: {e}", file=sys.stderr)
        # Return default dev config as fallback
        return DevConfig()

# Initialize settings
settings = setup_config()