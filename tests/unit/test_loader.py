"""Unit tests for the fail-closed configuration loader."""

import pytest

from config import loader
from config.base import BaseConfig


class TestSetupConfigFailClosed:
    """setup_config() must never fall back to dev defaults on error."""

    def test_unknown_app_env_raises(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "staging")
        with pytest.raises(RuntimeError, match="Unknown APP_ENV"):
            loader.setup_config()

    def test_missing_prod_env_file_raises(self, monkeypatch, tmp_path):
        monkeypatch.setenv("APP_ENV", "prod")
        monkeypatch.chdir(tmp_path)  # no env/prod.env here
        with pytest.raises(RuntimeError, match="not found"):
            loader.setup_config()

    def test_prod_debug_safeguard_raises(self, monkeypatch):
        class DebuggingProdConfig(BaseConfig):
            DEBUG: bool = True

        monkeypatch.setenv("APP_ENV", "prod")
        monkeypatch.setitem(loader.__dict__, "ProdConfig", DebuggingProdConfig)
        # env/prod.env exists in the repo; the safeguard must still trigger
        with pytest.raises(RuntimeError, match="DEBUG must be disabled"):
            loader.setup_config()

    def test_dev_without_env_file_uses_defaults(self, monkeypatch, tmp_path):
        monkeypatch.setenv("APP_ENV", "dev")
        monkeypatch.chdir(tmp_path)  # no env/dev.env here
        settings = loader.setup_config()
        assert settings.APP_ENV == "dev"
