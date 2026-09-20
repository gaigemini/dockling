import os
import sys
from dotenv import load_dotenv
from .base import BaseConfig
from .dev import DevConfig
from .test import TestConfig
from .prod import ProdConfig

# Environments that are allowed to start without an explicit env file.
_ENVS_ALLOWING_MISSING_FILE = {"dev", "test"}


def setup_config():
    """Setup configuration with fail-closed error handling.

    Any failure while loading the environment-specific configuration aborts
    startup (raises) instead of silently falling back to dev defaults, which
    would disable authentication (DISABLE_AUTH=True) and enable DEBUG.
    """
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

    if APP_ENV not in env_configs:
        raise RuntimeError(
            f"Unknown APP_ENV '{APP_ENV}'. Valid values: {', '.join(env_configs)}"
        )

    # Get config class for current environment
    ConfigClass = env_configs[APP_ENV]

    # Load environment-specific .env file
    env_file = f"env/{APP_ENV}.env"

    # Check if env file exists
    if not os.path.exists(env_file):
        if APP_ENV not in _ENVS_ALLOWING_MISSING_FILE:
            raise RuntimeError(
                f"Environment file {env_file} not found. "
                f"Refusing to start '{APP_ENV}' with built-in defaults."
            )
        print(f"⚠️  Environment file {env_file} not found, using defaults", file=sys.stderr)
        settings_instance = ConfigClass()
    else:
        print(f"📁 Loading config from: {env_file}", file=sys.stderr)
        try:
            settings_instance = ConfigClass(_env_file=env_file, _env_file_encoding='utf-8')
        except Exception as e:
            print(f"❌ Failed to load configuration: {e}", file=sys.stderr)
            raise RuntimeError(
                f"Configuration load failed for APP_ENV={APP_ENV}"
            ) from e

    # Critical production safeguard - deliberately outside any try/except so it
    # can never be swallowed by a broad handler.
    if APP_ENV == "prod" and settings_instance.DEBUG:
        raise RuntimeError("DEBUG must be disabled in production!")

    print(f"✅ Configuration loaded successfully for {APP_ENV} environment", file=sys.stderr)
    return settings_instance


# Initialize settings
settings = setup_config()
