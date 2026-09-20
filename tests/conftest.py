"""Shared pytest fixtures."""

import os

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import storage_service as storage_module


class FakeStorageService:
    """In-memory object storage double for API/unit tests."""

    def __init__(self) -> None:
        self.enabled = False
        self.bucket = "test-bucket"
        self.objects: dict = {}

    # Setup
    async def ensure_bucket(self) -> None:
        return None

    async def ensure_result_lifecycle(self) -> None:
        return None

    # Upload
    async def upload_file(self, local_path, object_key, content_type="application/octet-stream"):
        with open(local_path, "rb") as fh:
            self.objects[object_key] = fh.read()
        return object_key

    async def upload_bytes(self, object_key, data, content_type="application/octet-stream"):
        self.objects[object_key] = data
        return object_key

    # Download
    async def download_to_file(self, object_key, dest_path):
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, "wb") as fh:
            fh.write(self.objects[object_key])
        return dest_path

    async def get_object_bytes(self, object_key):
        return self.objects[object_key]

    # Delete / inspect
    async def delete_object(self, object_key):
        return self.objects.pop(object_key, None) is not None

    async def delete_prefix(self, prefix):
        keys = [k for k in self.objects if k.startswith(prefix)]
        for key in keys:
            self.objects.pop(key, None)
        return len(keys)

    async def object_exists(self, object_key):
        return object_key in self.objects

    async def list_keys(self, prefix, limit=1000):
        return [k for k in self.objects if k.startswith(prefix)][:limit]

    async def presign_get_url(self, object_key):
        return f"http://fake-minio/{self.bucket}/{object_key}"

    async def health(self):
        return True


@pytest.fixture
async def client():
    """Async client fixture for API testing (httpx >= 0.28 ASGITransport)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
def mock_settings(monkeypatch, tmp_path):
    """Mock settings for testing."""
    monkeypatch.setattr("config.loader.settings.DISABLE_AUTH", True)
    monkeypatch.setattr("config.loader.settings.TEMP_DIR", str(tmp_path))
    monkeypatch.setattr("config.loader.settings.MINIO_ENABLED", False)


@pytest.fixture(autouse=True)
def fake_storage(monkeypatch):
    """Install an in-memory storage service singleton for every test."""
    fake = FakeStorageService()
    monkeypatch.setattr(storage_module, "_storage_service", fake)
    yield fake
    monkeypatch.setattr(storage_module, "_storage_service", None)
