"""Unit tests for TaskWorker expiry, timeout and janitor logic."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

from app.models.task_model import TaskInfo, TaskStatus
from app.services.task_service import TaskService
from app.workers.task_worker import TaskWorker


def _worker(task_service, storage=None, callback=None) -> TaskWorker:
    return TaskWorker(
        task_service=task_service,
        conversion_service=MagicMock(),
        storage_service=storage or AsyncMock(),
        callback_service=callback,
    )


def _task(task_id: str, status: TaskStatus, **kwargs) -> TaskInfo:
    return TaskInfo(
        task_id=task_id,
        status=status,
        endpoint="convert",
        created_at=time.time(),
        **kwargs,
    )


class TestProcessTask:
    """Expiry and timeout handling in TaskWorker._process_task()."""

    async def test_expired_queued_task_is_skipped(self):
        now = time.time()
        service = AsyncMock()
        service.get_task.return_value = _task(
            "t-expired",
            TaskStatus.PENDING,
            queue_expires_at=now - 5,
        )
        worker = _worker(service)

        await worker._process_task("t-expired")

        service.update_task_status.assert_awaited_once()
        args, _ = service.update_task_status.call_args
        assert args[0] == "t-expired"
        assert args[1] == TaskStatus.EXPIRED
        service.ack_task.assert_awaited_once_with("t-expired")

    async def test_processing_timeout_marks_timeout(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.loader.settings.TEMP_DIR", str(tmp_path))
        input_file = tmp_path / "input.pdf"
        input_file.write_bytes(b"%PDF-1.4 fake")

        service = AsyncMock()
        service.get_task.return_value = _task(
            "t-slow",
            TaskStatus.PENDING,
            file_path=str(input_file),
            timeout_seconds=60,
        )
        worker = _worker(service)
        worker._dispatch = AsyncMock(side_effect=asyncio.TimeoutError())

        await worker._process_task("t-slow")

        statuses = [call.args[1] for call in service.update_task_status.await_args_list]
        assert statuses == [TaskStatus.PROCESSING, TaskStatus.TIMEOUT]
        service.ack_task.assert_awaited_once_with("t-slow")
        # Local input is cleaned up regardless of outcome
        assert not input_file.exists()

    async def test_terminal_task_is_acked_without_processing(self):
        service = AsyncMock()
        service.get_task.return_value = _task("t-done", TaskStatus.COMPLETED)
        worker = _worker(service)

        await worker._process_task("t-done")

        service.update_task_status.assert_not_awaited()
        service.ack_task.assert_awaited_once_with("t-done")


class TestJanitor:
    """Watchdog transitions for stalled and expired tasks."""

    async def test_janitor_transitions(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.loader.settings.TEMP_DIR", str(tmp_path))
        now = time.time()

        service = AsyncMock()
        service.list_tasks.return_value = [
            _task(
                "stale",
                TaskStatus.PROCESSING,
                started_at=now - 200,
                processing_deadline=now - 100,
            ),
            _task(
                "resume",
                TaskStatus.PROCESSING,
                started_at=now - 10,
                processing_deadline=now + 5000,
            ),
            _task(
                "expired",
                TaskStatus.PENDING,
                queue_expires_at=now - 10,
            ),
        ]
        worker = _worker(service)

        await worker._janitor_pass()

        transitions = {}
        for call in service.update_task_status.await_args_list:
            transitions[call.args[0]] = call.args[1]

        assert transitions["stale"] == TaskStatus.TIMEOUT
        assert transitions["expired"] == TaskStatus.EXPIRED
        service.ack_task.assert_any_await("stale")
        service.requeue_task.assert_awaited_once_with("resume")


class _TaskRedis:
    """Minimal async Redis double for the task queue/index hashes."""

    def __init__(self) -> None:
        self.hashes: dict = {}
        self.lists: dict = {}
        self.ttls: dict = {}

    async def llen(self, key):
        return len(self.lists.get(key, []))

    async def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)

    async def lrem(self, key, count, value):
        self.lists[key] = [v for v in self.lists.get(key, []) if v != value]

    async def lrange(self, key, start, end):
        return list(self.lists.get(key, []))

    async def zadd(self, key, mapping):
        pass

    async def zrevrange(self, key, start, end):
        return []

    async def zremrangebyscore(self, key, min_score, max_score):
        return 0

    async def hset(self, key, mapping=None, **kwargs):
        self.hashes.setdefault(key, {}).update(mapping or {})

    async def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    async def expire(self, key, ttl):
        self.ttls[key] = ttl

    async def delete(self, key):
        self.hashes.pop(key, None)


class TestResultStorage:
    """Results are externalized; Redis stores only the artifact reference."""

    async def test_successful_processing_stores_result_ref(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("config.loader.settings.TEMP_DIR", str(tmp_path))
        input_file = tmp_path / "input.pdf"
        input_file.write_bytes(b"%PDF-1.4 fake")

        redis = _TaskRedis()
        service = TaskService(redis)
        task = await service.submit_task(
            endpoint="convert",
            params={"output_type": "markdown"},
            file_path=str(input_file),
        )

        storage = AsyncMock()
        storage.upload_bytes = AsyncMock(return_value="results/x/result.json")
        worker = _worker(service, storage=storage)
        worker._dispatch = AsyncMock(return_value={
            "content": "# doc",
            "processing_time": 1.5,
            "metadata": {"page_count": 2, "file_type": "pdf"},
        })

        await worker._process_task(task.task_id)

        stored = await service.get_task(task.task_id)
        assert stored.status == TaskStatus.COMPLETED
        assert stored.result is None  # no inline result in Redis
        expected_key = f"results/{task.task_id}/result.json"
        assert stored.result_ref == expected_key
        assert stored.result_summary["page_count"] == 2
        storage.upload_bytes.assert_awaited()
        upload_args, _ = storage.upload_bytes.call_args
        assert upload_args[0] == expected_key
        # The task id was removed from the in-flight list
        assert redis.lists.get("task:processing", []) == []
