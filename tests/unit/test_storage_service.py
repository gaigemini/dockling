"""Unit tests for StorageService (MinIO + local fallback)."""

from unittest.mock import MagicMock

import pytest
from minio.error import S3Error

from app.services.storage_service import StorageService


def _s3_error(code: str = "NoSuchKey") -> S3Error:
    # minio S3Error signature: (response, code, message, resource, request_id, host_id, ...)
    return S3Error(None, code, f"{code} error", "/resource", "req-id", "host-id", "bucket", "key")


class TestLocalFallback:
    """StorageService in local-disk fallback mode (MINIO_ENABLED=False)."""

    @pytest.fixture
    def service(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.services.storage_service.settings.MINIO_ENABLED", False)
        monkeypatch.setattr("app.services.storage_service.settings.TEMP_DIR", str(tmp_path))
        return StorageService()

    async def test_roundtrip_bytes(self, service):
        await service.upload_bytes("results/t-1/result.json", b'{"ok": true}', "application/json")

        assert await service.object_exists("results/t-1/result.json")
        assert await service.get_object_bytes("results/t-1/result.json") == b'{"ok": true}'

    async def test_roundtrip_file(self, service, tmp_path):
        src = tmp_path / "input.pdf"
        src.write_bytes(b"%PDF-1.4 fake")
        key = await service.upload_file(str(src), "uploads/abc/input.pdf", "application/pdf")

        assert key == "uploads/abc/input.pdf"
        dest = tmp_path / "download" / "input.pdf"
        await service.download_to_file(key, str(dest))
        assert dest.read_bytes() == b"%PDF-1.4 fake"

    async def test_delete_object_and_prefix(self, service):
        await service.upload_bytes("results/a/result.json", b"1")
        await service.upload_bytes("results/a/extra.json", b"2")

        assert await service.delete_object("results/a/result.json") is True
        assert await service.delete_object("results/a/result.json") is False

        removed = await service.delete_prefix("results/a/")
        assert removed == 1
        assert await service.list_keys("results/") == []

    async def test_list_keys_and_presign(self, service):
        await service.upload_bytes("results/x/result.json", b"1")
        await service.upload_bytes("uploads/y/file.pdf", b"2")

        assert await service.list_keys("results/") == ["results/x/result.json"]
        assert await service.presign_get_url("results/x/result.json") is None

    async def test_health_and_bucket(self, service):
        await service.ensure_bucket()
        assert await service.health() is True
        # Lifecycle rules are a no-op in fallback mode
        await service.ensure_result_lifecycle()


class TestMinioMode:
    """StorageService in MinIO mode with a mocked Minio client."""

    @pytest.fixture
    def client(self):
        return MagicMock()

    @pytest.fixture
    def service(self, client, monkeypatch):
        monkeypatch.setattr("app.services.storage_service.settings.MINIO_ENABLED", True)
        return StorageService(client=client)

    async def test_upload_bytes_calls_put_object(self, service, client):
        key = await service.upload_bytes("results/t/result.json", b"data", "application/json")

        assert key == "results/t/result.json"
        args, kwargs = client.put_object.call_args
        assert args[0] == service.bucket
        assert args[1] == "results/t/result.json"
        assert kwargs["content_type"] == "application/json"

    async def test_presign_returns_url(self, service, client):
        client.presigned_get_object.return_value = "http://minio/presigned"
        url = await service.presign_get_url("results/t/result.json")
        assert url == "http://minio/presigned"

    async def test_delete_missing_object_returns_false(self, service, client):
        client.remove_object.side_effect = _s3_error("NoSuchKey")
        assert await service.delete_object("missing") is False

    async def test_object_exists_false_on_error(self, service, client):
        client.stat_object.side_effect = _s3_error("NoSuchKey")
        assert await service.object_exists("missing") is False

    async def test_health_reflects_bucket(self, service, client):
        client.bucket_exists.return_value = True
        assert await service.health() is True

        client.bucket_exists.side_effect = Exception("down")
        assert await service.health() is False

    async def test_result_lifecycle_rule_applied(self, service, client, monkeypatch):
        monkeypatch.setattr(
            "app.services.storage_service.settings.MINIO_RESULT_TTL_DAYS", 7
        )
        await service.ensure_result_lifecycle()

        args, _ = client.set_bucket_lifecycle.call_args
        assert args[0] == service.bucket
        lifecycle_config = args[1]
        rule = lifecycle_config.rules[0]
        assert rule.status == "Enabled"
        assert rule.expiration.days == 7

    async def test_list_keys_uses_client(self, service, client):
        obj = MagicMock()
        obj.object_name = "results/t/result.json"
        client.list_objects.return_value = [obj]

        keys = await service.list_keys("results/")
        assert keys == ["results/t/result.json"]
