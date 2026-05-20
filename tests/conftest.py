import pytest
from httpx import AsyncClient
from app.main import app


@pytest.fixture
async def client():
    """Async client fixture for API testing."""
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
def mock_settings(monkeypatch):
    """Mock settings for testing."""
    monkeypatch.setattr("config.loader.settings.DISABLE_AUTH", True)
    monkeypatch.setattr("config.loader.settings.UPLOAD_DIR", "tests/temp_uploads")
