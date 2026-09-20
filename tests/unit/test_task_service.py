"""Unit tests for TaskService with mocked Redis."""

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.task_model import TaskInfo, TaskStatus
from app.services.task_service import TaskService


@pytest.fixture
def mock_redis():
    """Create a mock async Redis client."""
    redis = AsyncMock()
    redis.hset = AsyncMock()
    redis.hgetall = AsyncMock(return_value={})
    redis.rpush = AsyncMock()
    redis.llen = AsyncMock(return_value=0)
    redis.zadd = AsyncMock()
    redis.zrevrange = AsyncMock(return_value=[])
    redis.expire = AsyncMock()
    return redis


@pytest.fixture
def task_service(mock_redis):
    """Create a TaskService with mocked Redis."""
    return TaskService(mock_redis)


# ------------------------------------------------------------------
# submit_task
# ------------------------------------------------------------------


class TestSubmitTask:
    """Tests for TaskService.submit_task()."""

    async def test_submit_task_success(self, task_service, mock_redis):
        """Task submission stores metadata and pushes to queue."""
        task = await task_service.submit_task(
            endpoint="convert",
            params={"enable_ocr": True, "output_type": "markdown"},
            file_path="/tmp/test.pdf",
        )

        assert task.status == TaskStatus.PENDING
        assert task.endpoint == "convert"
        assert task.file_path == "/tmp/test.pdf"
        assert task.params["enable_ocr"] is True
        assert task.task_id  # UUID generated

        # Verify Redis calls
        mock_redis.hset.assert_awaited_once()
        mock_redis.rpush.assert_awaited_once()
        mock_redis.zadd.assert_awaited_once()

    async def test_submit_task_queue_full(self, task_service, mock_redis):
        """Raises RuntimeError when queue is at max capacity."""
        mock_redis.llen.return_value = 100  # equals TASK_QUEUE_MAX_SIZE default

        with patch("app.services.task_service.settings") as mock_settings:
            mock_settings.TASK_QUEUE_MAX_SIZE = 100

            with pytest.raises(RuntimeError, match="Task queue is full"):
                await task_service.submit_task(
                    endpoint="convert",
                    params={},
                    file_path="/tmp/test.pdf",
                )

    async def test_submit_task_without_file(self, task_service, mock_redis):
        """Task can be submitted without a file_path (e.g. text-based endpoints)."""
        task = await task_service.submit_task(
            endpoint="convert",
            params={"content": "hello"},
            file_path=None,
        )

        assert task.file_path is None
        assert task.status == TaskStatus.PENDING


# ------------------------------------------------------------------
# get_task
# ------------------------------------------------------------------


class TestGetTask:
    """Tests for TaskService.get_task()."""

    async def test_get_task_found(self, task_service, mock_redis):
        """Returns TaskInfo when task exists in Redis."""
        now = time.time()
        mock_redis.hgetall.return_value = {
            "task_id": "abc-123",
            "status": "pending",
            "endpoint": "convert",
            "params": json.dumps({"enable_ocr": False}),
            "file_path": "/tmp/doc.pdf",
            "created_at": str(now),
            "started_at": "",
            "completed_at": "",
            "result": "",
            "error": "",
        }

        task = await task_service.get_task("abc-123")

        assert task is not None
        assert task.task_id == "abc-123"
        assert task.status == TaskStatus.PENDING
        assert task.endpoint == "convert"
        assert task.params["enable_ocr"] is False

    async def test_get_task_not_found(self, task_service, mock_redis):
        """Returns None when task does not exist."""
        mock_redis.hgetall.return_value = {}

        task = await task_service.get_task("nonexistent")

        assert task is None

    async def test_get_task_completed_with_result(self, task_service, mock_redis):
        """Returns task with result data when completed."""
        now = time.time()
        result_data = {"content": "# Hello", "processing_time": 1.23}
        mock_redis.hgetall.return_value = {
            "task_id": "done-123",
            "status": "completed",
            "endpoint": "convert",
            "params": "{}",
            "file_path": "/tmp/doc.pdf",
            "created_at": str(now - 10),
            "started_at": str(now - 5),
            "completed_at": str(now),
            "result": json.dumps(result_data),
            "error": "",
        }

        task = await task_service.get_task("done-123")

        assert task.status == TaskStatus.COMPLETED
        assert task.result == result_data
        assert task.processing_time is not None


# ------------------------------------------------------------------
# update_task_status
# ------------------------------------------------------------------


class TestUpdateTaskStatus:
    """Tests for TaskService.update_task_status()."""

    async def test_update_to_processing(self, task_service, mock_redis):
        """Sets started_at when transitioning to PROCESSING."""
        now = time.time()
        mock_redis.hgetall.return_value = {
            "task_id": "t-1",
            "status": "pending",
            "endpoint": "convert",
            "params": "{}",
            "file_path": "",
            "created_at": str(now),
            "started_at": "",
            "completed_at": "",
            "result": "",
            "error": "",
        }

        updated = await task_service.update_task_status("t-1", TaskStatus.PROCESSING)

        assert updated.status == TaskStatus.PROCESSING
        assert updated.started_at is not None
        mock_redis.hset.assert_awaited()

    async def test_update_to_completed(self, task_service, mock_redis):
        """Sets completed_at and stores result when transitioning to COMPLETED."""
        now = time.time()
        mock_redis.hgetall.return_value = {
            "task_id": "t-2",
            "status": "processing",
            "endpoint": "convert",
            "params": "{}",
            "file_path": "",
            "created_at": str(now - 10),
            "started_at": str(now - 5),
            "completed_at": "",
            "result": "",
            "error": "",
        }

        result = {"content": "markdown output"}
        updated = await task_service.update_task_status(
            "t-2", TaskStatus.COMPLETED, result=result
        )

        assert updated.status == TaskStatus.COMPLETED
        assert updated.completed_at is not None
        assert updated.result == result
        # TTL should be set on completed tasks
        mock_redis.expire.assert_awaited()

    async def test_update_to_failed(self, task_service, mock_redis):
        """Stores error message when transitioning to FAILED."""
        now = time.time()
        mock_redis.hgetall.return_value = {
            "task_id": "t-3",
            "status": "processing",
            "endpoint": "convert",
            "params": "{}",
            "file_path": "",
            "created_at": str(now - 10),
            "started_at": str(now - 5),
            "completed_at": "",
            "result": "",
            "error": "",
        }

        updated = await task_service.update_task_status(
            "t-3", TaskStatus.FAILED, error="OCR failed"
        )

        assert updated.status == TaskStatus.FAILED
        assert updated.error == "OCR failed"
        mock_redis.expire.assert_awaited()

    async def test_update_nonexistent_task(self, task_service, mock_redis):
        """Returns None when trying to update a task that doesn't exist."""
        mock_redis.hgetall.return_value = {}

        updated = await task_service.update_task_status("missing", TaskStatus.PROCESSING)

        assert updated is None


# ------------------------------------------------------------------
# list_tasks
# ------------------------------------------------------------------


class TestListTasks:
    """Tests for TaskService.list_tasks()."""

    async def test_list_tasks_empty(self, task_service, mock_redis):
        """Returns empty list when no tasks exist."""
        mock_redis.zrevrange.return_value = []

        tasks = await task_service.list_tasks()

        assert tasks == []

    async def test_list_tasks_returns_tasks(self, task_service, mock_redis):
        """Returns deserialized tasks from Redis index."""
        now = time.time()
        mock_redis.zrevrange.return_value = ["t-1", "t-2"]

        # First call returns t-1, second returns t-2
        mock_redis.hgetall.side_effect = [
            {
                "task_id": "t-1",
                "status": "completed",
                "endpoint": "convert",
                "params": "{}",
                "file_path": "",
                "created_at": str(now),
                "started_at": str(now),
                "completed_at": str(now),
                "result": "{}",
                "error": "",
            },
            {
                "task_id": "t-2",
                "status": "pending",
                "endpoint": "convert_n_chunk",
                "params": "{}",
                "file_path": "",
                "created_at": str(now),
                "started_at": "",
                "completed_at": "",
                "result": "",
                "error": "",
            },
        ]

        tasks = await task_service.list_tasks(limit=10, offset=0)

        assert len(tasks) == 2
        assert tasks[0].task_id == "t-1"
        assert tasks[1].task_id == "t-2"


# ------------------------------------------------------------------
# cancel_task
# ------------------------------------------------------------------


class TestCancelTask:
    """Tests for TaskService.cancel_task()."""

    async def test_cancel_pending_task(self, task_service, mock_redis):
        """Can cancel a task that is still pending."""
        now = time.time()
        mock_redis.hgetall.return_value = {
            "task_id": "c-1",
            "status": "pending",
            "endpoint": "convert",
            "params": "{}",
            "file_path": "",
            "created_at": str(now),
            "started_at": "",
            "completed_at": "",
            "result": "",
            "error": "",
        }

        cancelled = await task_service.cancel_task("c-1")

        assert cancelled is not None
        assert cancelled.status == TaskStatus.CANCELLED

    async def test_cancel_processing_task_fails(self, task_service, mock_redis):
        """Cannot cancel a task that is already processing."""
        now = time.time()
        mock_redis.hgetall.return_value = {
            "task_id": "c-2",
            "status": "processing",
            "endpoint": "convert",
            "params": "{}",
            "file_path": "",
            "created_at": str(now - 10),
            "started_at": str(now),
            "completed_at": "",
            "result": "",
            "error": "",
        }

        result = await task_service.cancel_task("c-2")

        assert result is None  # Cannot cancel

    async def test_cancel_nonexistent_task(self, task_service, mock_redis):
        """Returns None when cancelling a task that doesn't exist."""
        mock_redis.hgetall.return_value = {}

        result = await task_service.cancel_task("missing")

        assert result is None


# ------------------------------------------------------------------
# Timeouts / TTL
# ------------------------------------------------------------------


def _task_hash(task_id: str, status: str, **overrides) -> dict:
    """Build a raw Redis hash mapping for tests."""
    now = time.time()
    data = {
        "task_id": task_id,
        "status": status,
        "endpoint": "convert",
        "params": "{}",
        "file_path": "",
        "created_at": str(now - 10),
        "started_at": "",
        "completed_at": "",
        "result": "",
        "error": "",
    }
    data.update(overrides)
    return data


class TestTimeoutsAndTtl:
    """Queue deadline, processing deadline and terminal TTL (7-day alignment)."""

    async def test_submit_sets_queue_deadline_and_ttl(self, task_service, mock_redis):
        """New tasks get a queue expiry timestamp and a creation-time TTL."""
        task = await task_service.submit_task(endpoint="convert", params={})

        assert task.queue_expires_at is not None
        assert task.queue_expires_at > time.time()
        mock_redis.expire.assert_awaited()

    async def test_processing_sets_processing_deadline(self, task_service, mock_redis):
        """Transitioning to PROCESSING sets started_at and a soft deadline."""
        mock_redis.hgetall.return_value = _task_hash("t-1", "pending")

        updated = await task_service.update_task_status("t-1", TaskStatus.PROCESSING)

        assert updated.started_at is not None
        assert updated.processing_deadline is not None
        assert updated.processing_deadline > updated.started_at

    async def test_processing_deadline_capped_by_max(self, task_service, mock_redis):
        """A per-request timeout cannot exceed TASK_PROCESSING_TIMEOUT_MAX."""
        mock_redis.hgetall.return_value = _task_hash(
            "t-2", "pending", timeout_seconds="999999"
        )

        updated = await task_service.update_task_status("t-2", TaskStatus.PROCESSING)

        deadline_after_start = updated.processing_deadline - updated.started_at
        assert deadline_after_start <= 10800 + 1

    async def test_expired_and_timeout_are_terminal(self, task_service, mock_redis):
        """EXPIRED/TIMEOUT set completed_at and apply the result TTL."""
        mock_redis.hgetall.return_value = _task_hash(
            "t-3", "processing", started_at=str(time.time() - 5)
        )

        updated = await task_service.update_task_status(
            "t-3", TaskStatus.TIMEOUT, error="too slow"
        )

        assert updated.completed_at is not None
        assert updated.error == "too slow"
        mock_redis.expire.assert_awaited()
