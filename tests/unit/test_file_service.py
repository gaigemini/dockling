"""Unit tests for FileService (validation, MinIO store, resumable sessions)."""

from io import BytesIO

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

from app.models.document_model import UploadStatusEnum
from app.services import file_service as file_service_module
from app.services.file_service import FileService


class _FakeRedis:
    """Minimal async Redis double for upload sessions."""

    def __init__(self) -> None:
        self.hashes: dict = {}
        self.ttls: dict = {}
        self.deleted: list = []

    async def hset(self, key, mapping=None, **kwargs):
        self.hashes.setdefault(key, {}).update(mapping or {})

    async def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    async def hdel(self, key, *fields):
        for field in fields:
            self.hashes.get(key, {}).pop(field, None)

    async def expire(self, key, ttl):
        self.ttls[key] = ttl

    async def delete(self, key):
        self.deleted.append(key)
        self.hashes.pop(key, None)


@pytest.fixture
def fake_redis(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(file_service_module, "get_redis", lambda: fake)
    return fake


@pytest.fixture
def service():
    return FileService(None)


def _upload_file(content: bytes, filename: str = "sample.txt") -> UploadFile:
    return UploadFile(file=BytesIO(content), size=len(content), filename=filename)


class TestStoreUpload:
    """Direct uploads are validated then stored in object storage."""

    async def test_store_upload_roundtrip(self, service, fake_storage, tmp_path):
        original = b"hello world"

        object_key, safe_name = await service.store_upload(_upload_file(original))

        assert object_key.startswith("uploads/")
        assert object_key.endswith(safe_name)
        assert fake_storage.objects[object_key] == original
        # Local scratch must be cleaned up
        assert [p.name for p in tmp_path.iterdir() if p.is_file()] == []

    async def test_store_upload_rejects_unsupported_type(self, service):
        # ZIP magic bytes -> application/zip, not in the supported list
        zip_header = b"PK\x03\x04" + b"\x00" * 20

        with pytest.raises(HTTPException) as exc_info:
            await service.store_upload(_upload_file(zip_header, filename="archive.zip"))

        assert exc_info.value.status_code == 400


class TestResumableSessions:
    """Redis-backed resumable upload sessions."""

    async def test_chunk_retry_rewrites_in_place(
        self, service, fake_redis, fake_storage
    ):
        """Re-sending a range must overwrite in place (regression: O_APPEND bug)."""
        payload = b"Hello World!"
        session = await service.init_upload(
            "sample.txt", len(payload), "text/plain", user_id="u1"
        )

        # First half, then an identical retry (must NOT be appended at EOF),
        # then the second half.
        await service.append_upload(
            session.upload_id, payload[:6], f"bytes 0-5/{len(payload)}", user_id="u1"
        )
        await service.append_upload(
            session.upload_id, payload[:6], f"bytes 0-5/{len(payload)}", user_id="u1"
        )
        final = await service.append_upload(
            session.upload_id, payload[6:], f"bytes 6-11/{len(payload)}", user_id="u1"
        )

        assert final.status == UploadStatusEnum.COMPLETED
        assert final.received_size == len(payload)
        assert final.object_key.startswith("uploads/")
        assert fake_storage.objects[final.object_key] == payload

    async def test_append_rejects_wrong_owner(self, service, fake_redis):
        session = await service.init_upload("sample.txt", 10, "text/plain", user_id="u1")

        with pytest.raises(HTTPException) as exc_info:
            await service.append_upload(session.upload_id, b"12345", user_id="u2")

        assert exc_info.value.status_code == 403

    async def test_status_and_removal(self, service, fake_redis, fake_storage):
        session = await service.init_upload("sample.txt", 10, "text/plain", user_id="u1")

        loaded = await service.get_upload_status(session.upload_id)
        assert loaded is not None
        assert loaded.user_id == "u1"

        await service.remove_upload_session(session.upload_id)
        assert await service.get_upload_status(session.upload_id) is None
