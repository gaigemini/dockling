"""Integration tests for async task endpoints."""

import json
import time
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.models.task_model import TaskInfo, TaskStatus


@pytest.fixture
def mock_task_service():
    """Mock TaskService for integration tests."""
    service = AsyncMock()
    service.submit_task = AsyncMock()
    service.get_task = AsyncMock()
    service.list_tasks = AsyncMock(return_value=[])
    return service


@pytest.fixture
async def client_with_mock_task_service(mock_task_service):
    """Async client with mocked task_service on app.state."""
    original = getattr(app.state, "task_service", None)
    app.state.task_service = mock_task_service

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    # Restore
    app.state.task_service = original


# ------------------------------------------------------------------
# POST /api/v1/convert_async
# ------------------------------------------------------------------


class TestConvertAsync:
    """Tests for POST /api/v1/convert_async."""

    async def test_submit_convert_task(
        self, client_with_mock_task_service, mock_task_service
    ):
        """Submitting a file returns 202 with task_id."""
        now = time.time()
        mock_task_service.submit_task.return_value = TaskInfo(
            task_id="test-task-123",
            status=TaskStatus.PENDING,
            endpoint="convert",
            created_at=now,
        )

        response = await client_with_mock_task_service.post(
            "/api/v1/convert_async",
            files={"file": ("test.pdf", b"fake-pdf-content", "application/pdf")},
            data={"enable_ocr": "true", "output_type": "markdown"},
        )

        assert response.status_code == 202
        body = response.json()
        assert body["status"] == 0  # SUCCESS
        assert body["data"]["task_id"] == "test-task-123"
        assert "/api/v1/tasks/test-task-123" in body["data"]["poll_url"]

        # Verify submit_task was called
        mock_task_service.submit_task.assert_awaited_once()
        call_kwargs = mock_task_service.submit_task.call_args
        assert call_kwargs.kwargs["endpoint"] == "convert"

    async def test_submit_task_queue_full(
        self, client_with_mock_task_service, mock_task_service
    ):
        """Returns 503 when queue is full."""
        mock_task_service.submit_task.side_effect = RuntimeError("Task queue is full")

        response = await client_with_mock_task_service.post(
            "/api/v1/convert_async",
            files={"file": ("test.pdf", b"content", "application/pdf")},
        )

        assert response.status_code == 503

    async def test_submit_task_no_redis(
        self, client_with_mock_task_service,
    ):
        """Returns 503 when task_service is None (Redis unavailable)."""
        client_with_mock_task_service._transport.app.state.task_service = None

        response = await client_with_mock_task_service.post(
            "/api/v1/convert_async",
            files={"file": ("test.pdf", b"content", "application/pdf")},
        )

        assert response.status_code == 503


# ------------------------------------------------------------------
# POST /api/v1/convert_n_chunk_async
# ------------------------------------------------------------------


class TestConvertNChunkAsync:
    """Tests for POST /api/v1/convert_n_chunk_async."""

    async def test_submit_chunk_task(
        self, client_with_mock_task_service, mock_task_service
    ):
        """Submitting convert+chunk returns 202 with task_id."""
        now = time.time()
        mock_task_service.submit_task.return_value = TaskInfo(
            task_id="chunk-task-456",
            status=TaskStatus.PENDING,
            endpoint="convert_n_chunk",
            created_at=now,
        )

        response = await client_with_mock_task_service.post(
            "/api/v1/convert_n_chunk_async",
            files={"file": ("test.pdf", b"fake-pdf-content", "application/pdf")},
            data={
                "enable_ocr": "false",
                "max_tokens": "256",
                "chunk_type": "hybrid",
            },
        )

        assert response.status_code == 202
        body = response.json()
        assert body["data"]["task_id"] == "chunk-task-456"


# ------------------------------------------------------------------
# GET /api/v1/tasks/{task_id}
# ------------------------------------------------------------------


class TestGetTaskStatus:
    """Tests for GET /api/v1/tasks/{task_id}."""

    async def test_poll_pending_task(
        self, client_with_mock_task_service, mock_task_service
    ):
        """Polling a pending task returns pending status."""
        now = time.time()
        mock_task_service.get_task.return_value = TaskInfo(
            task_id="t-1",
            status=TaskStatus.PENDING,
            endpoint="convert",
            created_at=now,
        )

        response = await client_with_mock_task_service.get("/api/v1/tasks/t-1")

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["status"] == "pending"
        assert "result" not in body["data"]

    async def test_poll_processing_task(
        self, client_with_mock_task_service, mock_task_service
    ):
        """Polling a processing task returns processing status with started_at."""
        now = time.time()
        mock_task_service.get_task.return_value = TaskInfo(
            task_id="t-2",
            status=TaskStatus.PROCESSING,
            endpoint="convert",
            created_at=now - 10,
            started_at=now - 5,
        )

        response = await client_with_mock_task_service.get("/api/v1/tasks/t-2")

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["status"] == "processing"
        assert body["data"]["started_at"] is not None

    async def test_poll_completed_task(
        self, client_with_mock_task_service, mock_task_service
    ):
        """Polling a completed task returns a result_url (no inline result)."""
        now = time.time()
        mock_task_service.get_task.return_value = TaskInfo(
            task_id="t-3",
            status=TaskStatus.COMPLETED,
            endpoint="convert",
            created_at=now - 60,
            started_at=now - 55,
            completed_at=now,
            result_ref="results/t-3/result.json",
            result_summary={"size_bytes": 1234, "page_count": 3},
        )

        response = await client_with_mock_task_service.get("/api/v1/tasks/t-3")

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["status"] == "completed"
        assert "result" not in body["data"]
        assert "result_url" in body["data"]
        assert body["data"]["result_summary"]["page_count"] == 3

    async def test_poll_failed_task(
        self, client_with_mock_task_service, mock_task_service
    ):
        """Polling a failed task returns error message."""
        now = time.time()
        mock_task_service.get_task.return_value = TaskInfo(
            task_id="t-4",
            status=TaskStatus.FAILED,
            endpoint="convert",
            created_at=now - 60,
            started_at=now - 55,
            completed_at=now,
            error="Document conversion failed: unsupported format",
        )

        response = await client_with_mock_task_service.get("/api/v1/tasks/t-4")

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["status"] == "failed"
        assert "unsupported format" in body["data"]["error"]

    async def test_poll_nonexistent_task(
        self, client_with_mock_task_service, mock_task_service
    ):
        """Returns 404 for a task that doesn't exist."""
        mock_task_service.get_task.return_value = None

        response = await client_with_mock_task_service.get("/api/v1/tasks/nonexistent")

        assert response.status_code == 404


# ------------------------------------------------------------------
# GET /api/v1/tasks
# ------------------------------------------------------------------


class TestListTasks:
    """Tests for GET /api/v1/tasks."""

    async def test_list_tasks_empty(
        self, client_with_mock_task_service, mock_task_service
    ):
        """Returns empty list when no tasks exist."""
        mock_task_service.list_tasks.return_value = []

        response = await client_with_mock_task_service.get("/api/v1/tasks")

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["tasks"] == []
        assert body["data"]["count"] == 0

    async def test_list_tasks_with_results(
        self, client_with_mock_task_service, mock_task_service
    ):
        """Returns list of task summaries."""
        now = time.time()
        mock_task_service.list_tasks.return_value = [
            TaskInfo(
                task_id="t-1",
                status=TaskStatus.COMPLETED,
                endpoint="convert",
                created_at=now - 100,
                started_at=now - 90,
                completed_at=now - 50,
            ),
            TaskInfo(
                task_id="t-2",
                status=TaskStatus.PENDING,
                endpoint="convert_n_chunk",
                created_at=now,
            ),
        ]

        response = await client_with_mock_task_service.get("/api/v1/tasks?limit=10&offset=0")

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["count"] == 2
        assert body["data"]["tasks"][0]["task_id"] == "t-1"
        assert body["data"]["tasks"][1]["task_id"] == "t-2"
