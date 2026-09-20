"""Unit tests for CallbackService (webhook delivery)."""

import contextlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.task_model import TaskInfo, TaskStatus
from app.services import callback_service as callback_module
from app.services.callback_service import CallbackService


def _completed_task(callback_url: str | None) -> TaskInfo:
    return TaskInfo(
        task_id="t-1",
        status=TaskStatus.COMPLETED,
        endpoint="convert",
        callback_url=callback_url,
        created_at=100.0,
        started_at=101.0,
        completed_at=142.0,
        result_summary={"page_count": 3},
    )


def _fake_http_client(response=None, side_effect=None):
    """Build a fake get_correlated_client context manager."""
    client = MagicMock()
    client.post = AsyncMock(return_value=response, side_effect=side_effect)

    @contextlib.asynccontextmanager
    async def _factory(*args, **kwargs):
        yield client

    return _factory, client


class TestCallbackService:
    """Tests for CallbackService.notify()."""

    @pytest.fixture
    def service(self):
        return CallbackService()

    async def test_no_callback_url_is_noop(self, service, monkeypatch):
        factory, client = _fake_http_client()
        monkeypatch.setattr(callback_module, "get_correlated_client", factory)

        result = await service.notify(_completed_task(None))

        assert result is False
        client.post.assert_not_awaited()

    async def test_invalid_scheme_rejected(self, service, monkeypatch):
        factory, client = _fake_http_client()
        monkeypatch.setattr(callback_module, "get_correlated_client", factory)

        result = await service.notify(_completed_task("ftp://example.com/hook"))

        assert result is False
        client.post.assert_not_awaited()

    async def test_successful_delivery_is_signed(self, service, monkeypatch):
        response = MagicMock(status_code=200)
        factory, client = _fake_http_client(response=response)
        monkeypatch.setattr(callback_module, "get_correlated_client", factory)
        # Allowlist bypasses DNS/SSRF checks for the test host
        monkeypatch.setattr(
            "app.services.callback_service.settings.CALLBACK_ALLOWED_HOSTS",
            "example.com",
        )

        result = await service.notify(
            _completed_task("https://example.com/hook"),
            result_url="http://minio/presigned",
        )

        assert result is True
        client.post.assert_awaited_once()
        _args, kwargs = client.post.call_args
        assert kwargs["headers"]["X-Task-Id"] == "t-1"
        assert kwargs["headers"]["X-Signature"].startswith("sha256=")
        assert kwargs["json"]["result_url"] == "http://minio/presigned"
        assert kwargs["json"]["status"] == "completed"

    async def test_retries_then_permanent_failure(self, service, monkeypatch):
        factory, client = _fake_http_client(side_effect=RuntimeError("boom"))
        monkeypatch.setattr(callback_module, "get_correlated_client", factory)
        monkeypatch.setattr(
            "app.services.callback_service.settings.CALLBACK_ALLOWED_HOSTS",
            "example.com",
        )
        monkeypatch.setattr(
            "app.services.callback_service.settings.CALLBACK_MAX_RETRIES", 2
        )
        monkeypatch.setattr(
            "app.services.callback_service.asyncio.sleep", AsyncMock()
        )

        result = await service.notify(_completed_task("https://example.com/hook"))

        assert result is False
        assert client.post.await_count == 2

    async def test_non_2xx_response_is_retried(self, service, monkeypatch):
        response = MagicMock(status_code=500)
        factory, client = _fake_http_client(response=response)
        monkeypatch.setattr(callback_module, "get_correlated_client", factory)
        monkeypatch.setattr(
            "app.services.callback_service.settings.CALLBACK_ALLOWED_HOSTS",
            "example.com",
        )
        monkeypatch.setattr(
            "app.services.callback_service.settings.CALLBACK_MAX_RETRIES", 1
        )

        result = await service.notify(_completed_task("https://example.com/hook"))

        assert result is False
        assert client.post.await_count == 1
