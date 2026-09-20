"""Service for managing async conversion tasks backed by Redis."""

import json
import time
import uuid
from typing import Any, Dict, List, Optional

import redis.asyncio as aioredis

from config import settings
from app.models.task_model import TERMINAL_STATUSES, TaskInfo, TaskStatus
from app.services.base_service import BaseService

# Redis key prefixes / constants
_TASK_KEY_PREFIX = "task:"
_TASK_QUEUE_KEY = "task:queue"
_TASK_PROCESSING_KEY = "task:processing"  # reliable-queue in-flight list
_TASK_INDEX_KEY = "task:index"  # sorted set scored by created_at for listing


class TaskService(BaseService):
    """Manages async task lifecycle: submit, poll, update, cancel.

    Redis data layout
    -----------------
    * ``task:{task_id}`` – Hash storing full :class:`TaskInfo` fields.
    * ``task:queue`` – FIFO list of pending task_ids consumed by the worker.
    * ``task:processing`` – In-flight list. The worker moves ids here atomically
      via ``BLMOVE`` and removes them only on terminal states, so a crashed
      worker never loses a task.
    * ``task:index`` – Sorted set (score = created_at) for listing recent tasks.
    """

    def __init__(self, redis_client: aioredis.Redis, logger=None) -> None:
        super().__init__(logger)
        self._redis = redis_client

    @property
    def redis(self) -> aioredis.Redis:
        """Shared Redis client (public accessor for the worker)."""
        return self._redis

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def submit_task(
        self,
        endpoint: str,
        params: Dict[str, Any],
        file_path: Optional[str] = None,
        file_key: Optional[str] = None,
        callback_url: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
    ) -> TaskInfo:
        """Create a new pending task and push it onto the work queue.

        Args:
            endpoint: Name of the conversion endpoint (e.g. ``"convert"``, ``"convert_n_chunk"``).
            params: Serialized request parameters (form fields, flags, etc.).
            file_path: Legacy local path of the uploaded file (dev fallback).
            file_key: Object storage key of the uploaded input file.
            callback_url: Optional webhook URL notified on terminal status.
            timeout_seconds: Optional per-request max processing time override.

        Returns:
            The newly created :class:`TaskInfo` with status ``PENDING``.

        Raises:
            RuntimeError: If the queue has reached ``TASK_QUEUE_MAX_SIZE``.
        """
        queue_len = await self._redis.llen(_TASK_QUEUE_KEY)
        if queue_len >= settings.TASK_QUEUE_MAX_SIZE:
            raise RuntimeError(
                f"Task queue is full ({settings.TASK_QUEUE_MAX_SIZE}). "
                "Please try again later."
            )

        task_id = str(uuid.uuid4())
        now = time.time()

        task = TaskInfo(
            task_id=task_id,
            status=TaskStatus.PENDING,
            endpoint=endpoint,
            params=params,
            file_path=file_path,
            file_key=file_key,
            callback_url=callback_url,
            timeout_seconds=timeout_seconds,
            queue_expires_at=now + settings.TASK_QUEUE_TIMEOUT,
            created_at=now,
        )

        # Persist task hash
        await self._save_task(task)

        # Push to FIFO queue for the worker
        await self._redis.rpush(_TASK_QUEUE_KEY, task_id)

        # Add to sorted-set index (score = created_at) for listing
        await self._redis.zadd(_TASK_INDEX_KEY, {task_id: now})

        # Bound the key lifetime so a never-processed task cannot live forever.
        await self._redis.expire(
            f"{_TASK_KEY_PREFIX}{task_id}",
            settings.TASK_QUEUE_TIMEOUT
            + settings.TASK_PROCESSING_TIMEOUT
            + settings.TASK_RESULT_TTL,
        )

        self.logger.info(f"Task submitted: {task_id}", extra={
            "task_id": task_id,
            "endpoint": endpoint,
            "file_key": file_key,
            "file_path": file_path,
            "callback_url": callback_url,
            "queue_expires_at": task.queue_expires_at,
        })

        return task

    async def get_task(self, task_id: str) -> Optional[TaskInfo]:
        """Retrieve full task state from Redis.

        Returns:
            :class:`TaskInfo` if found, ``None`` otherwise.
        """
        raw = await self._redis.hgetall(f"{_TASK_KEY_PREFIX}{task_id}")
        if not raw:
            return None
        return self._deserialize(raw)

    async def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        result_ref: Optional[str] = None,
        result_summary: Optional[Dict[str, Any]] = None,
    ) -> Optional[TaskInfo]:
        """Transition a task to a new status and optionally store result/error.

        Sets ``started_at``/``processing_deadline`` when transitioning to
        ``PROCESSING`` and ``completed_at`` on terminal states
        (``COMPLETED``/``FAILED``/``CANCELLED``/``EXPIRED``/``TIMEOUT``).
        A 7-day TTL is applied on terminal states so status and result
        artifact expire together.

        Returns:
            Updated :class:`TaskInfo`, or ``None`` if the task was not found.
        """
        task = await self.get_task(task_id)
        if task is None:
            self.logger.warning(f"Cannot update non-existent task: {task_id}")
            return None

        now = time.time()
        task.status = status

        if status == TaskStatus.PROCESSING:
            task.started_at = now
            effective_timeout = self._effective_timeout(task.timeout_seconds)
            task.processing_deadline = now + effective_timeout
        elif status in TERMINAL_STATUSES:
            task.completed_at = now
            if result is not None:
                task.result = result
            if result_ref is not None:
                task.result_ref = result_ref
            if result_summary is not None:
                task.result_summary = result_summary
            if error is not None:
                task.error = error

        await self._save_task(task)

        # Apply TTL on terminal states so Redis auto-cleans in sync with MinIO.
        if status in TERMINAL_STATUSES:
            await self._redis.expire(
                f"{_TASK_KEY_PREFIX}{task_id}",
                settings.TASK_RESULT_TTL,
            )

        self.logger.info(f"Task {task_id} -> {status.value}", extra={
            "task_id": task_id,
            "status": status.value,
        })

        return task

    async def list_tasks(
        self,
        limit: int = 20,
        offset: int = 0,
    ) -> List[TaskInfo]:
        """List recent tasks ordered by creation time (newest first).

        Args:
            limit: Maximum number of tasks to return.
            offset: Number of tasks to skip (for pagination).

        Returns:
            List of :class:`TaskInfo` objects.
        """
        # Reverse range to get newest first
        task_ids = await self._redis.zrevrange(
            _TASK_INDEX_KEY,
            start=offset,
            end=offset + limit - 1,
        )

        tasks: List[TaskInfo] = []
        for tid in task_ids:
            task = await self.get_task(tid)
            if task is not None:
                tasks.append(task)

        return tasks

    async def cancel_task(self, task_id: str) -> Optional[TaskInfo]:
        """Cancel a task if it is still pending.

        Only tasks with status ``PENDING`` can be cancelled.  The task is
        *not* removed from the queue list (the worker will skip it when
        it sees the ``CANCELLED`` status).

        Returns:
            Updated :class:`TaskInfo`, or ``None`` if not found or not cancellable.
        """
        task = await self.get_task(task_id)
        if task is None:
            return None

        if task.status != TaskStatus.PENDING:
            self.logger.warning(
                f"Cannot cancel task {task_id}: current status is {task.status.value}"
            )
            return None

        return await self.update_task_status(task_id, TaskStatus.CANCELLED)

    # ------------------------------------------------------------------
    # Reliable queue helpers (used by the worker / janitor)
    # ------------------------------------------------------------------

    async def ack_task(self, task_id: str) -> None:
        """Remove a task id from the in-flight ``task:processing`` list."""
        await self._redis.lrem(_TASK_PROCESSING_KEY, 0, task_id)

    async def requeue_task(self, task_id: str) -> None:
        """Move a stranded in-flight task back onto the pending queue."""
        await self._redis.lrem(_TASK_PROCESSING_KEY, 0, task_id)
        await self._redis.rpush(_TASK_QUEUE_KEY, task_id)
        self.logger.info(f"Requeued stranded task: {task_id}", extra={"task_id": task_id})

    async def get_processing_ids(self) -> List[str]:
        """Return all task ids currently marked in-flight."""
        return await self._redis.lrange(_TASK_PROCESSING_KEY, 0, -1)

    async def remove_stale_index_entries(self, older_than: float) -> int:
        """Drop index entries whose score is older than ``older_than`` (epoch)."""
        return await self._redis.zremrangebyscore(_TASK_INDEX_KEY, 0, older_than)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _effective_timeout(requested: Optional[int]) -> int:
        """Resolve the per-task processing timeout, bounded by the global cap."""
        timeout = requested if requested and requested > 0 else settings.TASK_PROCESSING_TIMEOUT
        return min(timeout, settings.TASK_PROCESSING_TIMEOUT_MAX)

    async def _save_task(self, task: TaskInfo) -> None:
        """Persist the full task hash to Redis."""
        key = f"{_TASK_KEY_PREFIX}{task.task_id}"
        mapping: Dict[str, str] = {
            "task_id": task.task_id,
            "status": task.status.value,
            "endpoint": task.endpoint,
            "params": json.dumps(task.params),
            "file_path": task.file_path or "",
            "file_key": task.file_key or "",
            "callback_url": task.callback_url or "",
            "timeout_seconds": str(task.timeout_seconds) if task.timeout_seconds else "",
            "queue_expires_at": str(task.queue_expires_at) if task.queue_expires_at else "",
            "processing_deadline": str(task.processing_deadline) if task.processing_deadline else "",
            "created_at": str(task.created_at),
            "started_at": str(task.started_at) if task.started_at else "",
            "completed_at": str(task.completed_at) if task.completed_at else "",
            "result": json.dumps(task.result) if task.result else "",
            "result_ref": task.result_ref or "",
            "result_summary": json.dumps(task.result_summary) if task.result_summary else "",
            "error": task.error or "",
        }
        await self._redis.hset(key, mapping=mapping)

    @staticmethod
    def _deserialize(raw: Dict[str, str]) -> TaskInfo:
        """Convert a Redis hash back into a :class:`TaskInfo`."""

        def _opt_float(val: str) -> Optional[float]:
            return float(val) if val else None

        def _opt_int(val: str) -> Optional[int]:
            return int(val) if val else None

        def _opt_dict(val: str) -> Optional[Dict[str, Any]]:
            return json.loads(val) if val else None

        return TaskInfo(
            task_id=raw["task_id"],
            status=TaskStatus(raw["status"]),
            endpoint=raw["endpoint"],
            params=json.loads(raw.get("params", "{}")) if raw.get("params") else {},
            file_path=raw.get("file_path") or None,
            file_key=raw.get("file_key") or None,
            callback_url=raw.get("callback_url") or None,
            timeout_seconds=_opt_int(raw.get("timeout_seconds", "")),
            queue_expires_at=_opt_float(raw.get("queue_expires_at", "")),
            processing_deadline=_opt_float(raw.get("processing_deadline", "")),
            created_at=float(raw["created_at"]),
            started_at=_opt_float(raw.get("started_at", "")),
            completed_at=_opt_float(raw.get("completed_at", "")),
            result=_opt_dict(raw.get("result", "")),
            result_ref=raw.get("result_ref") or None,
            result_summary=_opt_dict(raw.get("result_summary", "")),
            error=raw.get("error") or None,
        )
