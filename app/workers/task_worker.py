"""Background worker that consumes tasks from the Redis queue and runs conversions.

Reliability model
-----------------
* Dequeue uses ``BLMOVE task:queue -> task:processing`` so a crashed worker
  never loses a task; ids are removed from ``task:processing`` only when the
  task reaches a terminal state.
* The worker enforces a soft processing timeout via ``asyncio.wait_for``. The
  Docling converter runs on an in-process (GPU-warmed) thread pool, so a timed
  out thread keeps running until it completes - only the task *status* is
  guaranteed to transition. The janitor guarantees consistency for tasks that
  stall because the worker crashed.
* Completed results are uploaded to object storage (MinIO); Redis stores only
  status, summary and the artifact key. Redis TTL (7 days) is aligned with the
  MinIO ``results/`` lifecycle rule.
"""

import asyncio
import json
import shutil
import time
from pathlib import Path
from typing import Optional, Set, Tuple

from docling_core.types.doc.base import ImageRefMode

from config import get_service_logger, settings
from app.models.document_model import ChunkType, OutputType
from app.models.task_model import TERMINAL_STATUSES, TaskInfo, TaskStatus
from app.services.callback_service import CallbackService
from app.services.conversion_service import ConversionService
from app.services.storage_service import StorageService
from app.services.task_service import (
    TaskService,
    _TASK_PROCESSING_KEY,
    _TASK_QUEUE_KEY,
)
from app.utils.params import build_page_range

_logger = get_service_logger("task_worker")

# Sentinel used to signal the worker to shut down gracefully.
_SHUTDOWN_SENTINEL = "__SHUTDOWN__"

# Freshness window for local temp files before the janitor sweeps them.
_TEMP_SWEEP_GRACE_SECONDS = 3600

# Run the (heavier) dangling-results sweep every N janitor passes.
_RESULTS_SWEEP_EVERY_N_PASSES = 60


class TaskWorker:
    """Continuously polls the Redis task queue and executes conversions.

    Designed to run as ``asyncio.Task`` objects inside the FastAPI lifespan
    context: one consumer loop plus one janitor/watchdog loop.
    """

    def __init__(
        self,
        task_service: TaskService,
        conversion_service: ConversionService,
        storage_service: StorageService,
        callback_service: Optional[CallbackService] = None,
    ) -> None:
        self._task_service = task_service
        self._conversion_service = conversion_service
        self._storage = storage_service
        self._callback = callback_service
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._janitor: Optional[asyncio.Task] = None
        self._semaphore = asyncio.Semaphore(max(1, settings.WORKER_CONCURRENCY))
        self._active_ids: Set[str] = set()
        self._background_tasks: Set[asyncio.Task] = set()
        self._janitor_passes = 0

    @property
    def is_running(self) -> bool:
        """Public flag - prefer this over reading ``_running``."""
        return self._running

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the consumer and janitor loops as background asyncio tasks."""
        if self._running:
            _logger.warning("Worker is already running")
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="task-worker")
        self._janitor = asyncio.create_task(self._janitor_loop(), name="task-janitor")
        _logger.info(
            f"Task worker started (concurrency={settings.WORKER_CONCURRENCY}, "
            f"processing timeout={settings.TASK_PROCESSING_TIMEOUT}s)"
        )

    async def stop(self) -> None:
        """Signal the worker to stop and wait for it to finish."""
        self._running = False

        # Push a sentinel so BLMOVE unblocks immediately
        try:
            await self._task_service.redis.rpush(_TASK_QUEUE_KEY, _SHUTDOWN_SENTINEL)
        except Exception:
            pass  # Redis may already be closed

        if self._task and not self._task.done():
            try:
                await asyncio.wait_for(self._task, timeout=30)
            except asyncio.TimeoutError:
                _logger.warning("Worker loop did not stop in time, cancelling")
                self._task.cancel()

        if self._janitor and not self._janitor.done():
            self._janitor.cancel()

        # Give in-flight conversions a short grace period, then cancel. A task
        # cancelled mid-conversion stays in ``task:processing`` and is
        # requeued by the janitor on the next startup.
        pending = [t for t in self._background_tasks if not t.done()]
        if pending:
            done, still_pending = await asyncio.wait(pending, timeout=5)
            for t in still_pending:
                t.cancel()

        _logger.info("Task worker stopped")

    # ------------------------------------------------------------------
    # Main consumer loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Blocking loop: BLMOVE from queue to processing, dispatch, repeat."""
        redis = self._task_service.redis

        while self._running:
            try:
                # Atomic move with 5-second timeout to allow periodic shutdown checks
                task_id = await redis.blmove(
                    _TASK_QUEUE_KEY, _TASK_PROCESSING_KEY, 5, "LEFT", "RIGHT"
                )
                if task_id is None:
                    continue  # timeout, try again

                # Shutdown sentinel
                if task_id == _SHUTDOWN_SENTINEL:
                    await redis.lrem(_TASK_PROCESSING_KEY, 0, _SHUTDOWN_SENTINEL)
                    _logger.info("Received shutdown sentinel, exiting worker loop")
                    break

                # Bound concurrency (GPU-bound conversions)
                await self._semaphore.acquire()
                bg = asyncio.create_task(self._process_guarded(task_id))
                self._background_tasks.add(bg)
                bg.add_done_callback(self._background_tasks.discard)

            except asyncio.CancelledError:
                _logger.info("Worker loop cancelled")
                break
            except TimeoutError:
                # Redis socket timeout - transient, just retry
                _logger.warning("Redis socket timeout, retrying...")
                await asyncio.sleep(1)
            except Exception as exc:
                _logger.error(f"Worker loop error: {exc}", exc_info=True)
                # Back off briefly to avoid tight error loops
                await asyncio.sleep(2)

        self._running = False

    async def _process_guarded(self, task_id: str) -> None:
        """Run one task, tracking it as active and releasing the semaphore."""
        self._active_ids.add(task_id)
        try:
            await self._process_task(task_id)
        except Exception as exc:
            _logger.error(
                f"Unhandled error while processing task {task_id}: {exc}",
                exc_info=True,
            )
        finally:
            self._active_ids.discard(task_id)
            self._semaphore.release()

    # ------------------------------------------------------------------
    # Task execution
    # ------------------------------------------------------------------

    async def _process_task(self, task_id: str) -> None:
        """Execute a single task end-to-end."""
        task = await self._task_service.get_task(task_id)
        if task is None:
            _logger.warning(f"Task {task_id} not found in Redis, skipping")
            await self._task_service.ack_task(task_id)
            return

        # Already finished (cancelled/expired/timed out or completed elsewhere)
        if task.status in TERMINAL_STATUSES:
            _logger.info(
                f"Task {task_id} already in terminal state ({task.status.value}), skipping"
            )
            if task.status == TaskStatus.CANCELLED:
                await self._cleanup_input(task)
            await self._task_service.ack_task(task_id)
            return

        # Queue expiry check - do not waste GPU time on stale work.
        now = time.time()
        if task.queue_expires_at and now > task.queue_expires_at:
            _logger.info(f"Task {task_id} expired while waiting in queue")
            await self._task_service.update_task_status(
                task_id,
                TaskStatus.EXPIRED,
                error="Expired while waiting in queue",
            )
            await self._cleanup_input(task)
            await self._task_service.ack_task(task_id)
            await self._maybe_notify(task_id)
            return

        _logger.info(f"Processing task {task_id} ({task.endpoint})", extra={
            "task_id": task_id,
            "endpoint": task.endpoint,
        })

        # Mark as processing (also (re)sets started_at + processing_deadline)
        await self._task_service.update_task_status(task_id, TaskStatus.PROCESSING)

        effective_timeout = min(
            task.timeout_seconds or settings.TASK_PROCESSING_TIMEOUT,
            settings.TASK_PROCESSING_TIMEOUT_MAX,
        )
        local_path: Optional[str] = None

        try:
            local_path, _filename = await self._prepare_input(task)

            # NOTE: soft timeout - the backing Docling thread continues until
            # it finishes; only the task status is guaranteed to change.
            result_data = await asyncio.wait_for(
                self._dispatch(task.endpoint, task.params, local_path),
                timeout=effective_timeout,
            )

            result_ref, summary = await self._store_result(task_id, result_data, task)
            await self._task_service.update_task_status(
                task_id,
                TaskStatus.COMPLETED,
                result_ref=result_ref,
                result_summary=summary,
            )
            _logger.info(f"Task {task_id} completed successfully", extra={
                "task_id": task_id,
                "result_ref": result_ref,
            })

        except asyncio.TimeoutError:
            _logger.error(
                f"Task {task_id} exceeded max processing time ({effective_timeout}s)"
            )
            await self._task_service.update_task_status(
                task_id,
                TaskStatus.TIMEOUT,
                error=f"Exceeded max processing time of {effective_timeout}s",
            )
        except Exception as exc:
            _logger.error(f"Task {task_id} failed: {exc}", exc_info=True)
            await self._task_service.update_task_status(
                task_id, TaskStatus.FAILED, error=str(exc)
            )
        finally:
            await self._cleanup_input(task, local_path)
            await self._task_service.ack_task(task_id)
            await self._maybe_notify(task_id)

    # ------------------------------------------------------------------
    # Input / output helpers
    # ------------------------------------------------------------------

    async def _prepare_input(self, task: TaskInfo) -> Tuple[str, str]:
        """Download the task input to a local scratch path.

        Returns:
            ``(local_path, filename)``

        Raises:
            FileNotFoundError: If the task has no usable input reference.
        """
        if task.file_key:
            filename = Path(task.file_key).name
            dest = Path(settings.TEMP_DIR) / task.task_id / filename
            await self._storage.download_to_file(task.file_key, str(dest))
            return str(dest), filename

        if task.file_path and Path(task.file_path).exists():
            return task.file_path, Path(task.file_path).name

        raise FileNotFoundError(
            f"Task {task.task_id}: no input file available "
            f"(file_key={task.file_key}, file_path={task.file_path})"
        )

    async def _store_result(
        self,
        task_id: str,
        result_data: dict,
        task: TaskInfo,
    ) -> Tuple[str, dict]:
        """Upload the result artifact to object storage and build its summary."""
        payload = json.dumps(result_data, default=str).encode("utf-8")
        key = f"{settings.MINIO_RESULT_PREFIX}/{task_id}/result.json"
        await self._storage.upload_bytes(key, payload, "application/json")

        summary = {
            "size_bytes": len(payload),
            "endpoint": task.endpoint,
            "output_type": task.params.get("output_type"),
        }
        if isinstance(result_data, dict):
            metadata = result_data.get("metadata")
            if isinstance(metadata, dict):
                summary["page_count"] = metadata.get("page_count")
            if "total_chunks" in result_data:
                summary["total_chunks"] = result_data["total_chunks"]
            if "processing_time" in result_data:
                summary["processing_time"] = result_data["processing_time"]
            conversion = result_data.get("conversion")
            if isinstance(conversion, dict) and isinstance(conversion.get("metadata"), dict):
                summary["page_count"] = conversion["metadata"].get(
                    "page_count", summary.get("page_count")
                )

        return key, summary

    async def _cleanup_input(
        self,
        task: TaskInfo,
        local_path: Optional[str] = None,
    ) -> None:
        """Remove local scratch files and (per config) the input object."""
        # Local scratch directory for this task
        task_dir = Path(settings.TEMP_DIR) / task.task_id
        try:
            if task_dir.exists():
                await asyncio.to_thread(shutil.rmtree, task_dir, True)
        except Exception as exc:
            _logger.warning(f"Failed to remove temp dir {task_dir}: {exc}")

        # Legacy local input path
        if task.file_path:
            try:
                path = Path(task.file_path)
                if path.exists():
                    await asyncio.to_thread(path.unlink)
            except Exception as exc:
                _logger.warning(f"Failed to clean up file {task.file_path}: {exc}")

        # Object storage input
        if task.file_key and settings.MINIO_DELETE_INPUT_ON_COMPLETE:
            try:
                await self._storage.delete_object(task.file_key)
            except Exception as exc:
                _logger.warning(f"Failed to delete input object {task.file_key}: {exc}")

    async def _maybe_notify(self, task_id: str) -> None:
        """Send the webhook for terminal tasks (never alters the result)."""
        if self._callback is None:
            return
        try:
            task = await self._task_service.get_task(task_id)
            if task is None or not task.callback_url or not task.is_terminal:
                return
            result_url = None
            if task.status == TaskStatus.COMPLETED and task.result_ref:
                result_url = await self._storage.presign_get_url(task.result_ref)
            await self._callback.notify(task, result_url=result_url)
        except Exception as exc:
            _logger.warning(f"Callback dispatch error for task {task_id}: {exc}")

    # ------------------------------------------------------------------
    # Janitor / watchdog
    # ------------------------------------------------------------------

    async def _janitor_loop(self) -> None:
        """Periodically recover stalled tasks and sweep stale artifacts."""
        while self._running:
            try:
                await asyncio.sleep(settings.JANITOR_INTERVAL)
                if not self._running:
                    break
                await self._janitor_pass()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _logger.error(f"Janitor error: {exc}", exc_info=True)

    async def _janitor_pass(self) -> None:
        """One watchdog sweep over recent tasks and artifacts."""
        now = time.time()
        self._janitor_passes += 1

        tasks = await self._task_service.list_tasks(limit=200)
        for task in tasks:
            if task.task_id in self._active_ids:
                continue  # currently being processed by this worker

            if task.status == TaskStatus.PROCESSING:
                if task.processing_deadline and now > task.processing_deadline:
                    _logger.warning(
                        f"Watchdog: task {task.task_id} exceeded its processing deadline"
                    )
                    await self._task_service.update_task_status(
                        task.task_id,
                        TaskStatus.TIMEOUT,
                        error="Watchdog: processing deadline exceeded",
                    )
                    await self._task_service.ack_task(task.task_id)
                    await self._cleanup_input(task)
                    await self._maybe_notify(task.task_id)
                else:
                    # Stranded in-flight entry from a crashed worker -> requeue.
                    # NOTE: single-instance scope; multi-replica deployments
                    # would need per-instance ownership tokens.
                    await self._task_service.requeue_task(task.task_id)

            elif (
                task.status == TaskStatus.PENDING
                and task.queue_expires_at
                and now > task.queue_expires_at
            ):
                _logger.info(f"Watchdog: task {task.task_id} expired in queue")
                await self._task_service.update_task_status(
                    task.task_id,
                    TaskStatus.EXPIRED,
                    error="Expired while waiting in queue",
                )
                await self._cleanup_input(task)
                await self._maybe_notify(task.task_id)

        # Sweep index entries that are older than any live task can be.
        stale_cutoff = now - (
            settings.TASK_RESULT_TTL
            + settings.TASK_QUEUE_TIMEOUT
            + settings.TASK_PROCESSING_TIMEOUT
            + 86400
        )
        try:
            removed = await self._task_service.remove_stale_index_entries(stale_cutoff)
            if removed:
                _logger.info(f"Janitor removed {removed} stale index entries")
        except Exception as exc:
            _logger.warning(f"Index sweep failed: {exc}")

        await self._sweep_local_temp()

        if self._janitor_passes % _RESULTS_SWEEP_EVERY_N_PASSES == 0:
            await self._sweep_dangling_results()

    async def _sweep_local_temp(self) -> None:
        """Remove task scratch directories that are no longer needed."""
        root = Path(settings.TEMP_DIR)
        if not root.exists():
            return
        now = time.time()
        try:
            entries = await asyncio.to_thread(lambda: list(root.iterdir()))
        except Exception:
            return
        for entry in entries:
            try:
                if not entry.is_dir() or entry.name == "storage":
                    continue
                if entry.name in self._active_ids:
                    continue
                age = now - entry.stat().st_mtime
                if age > _TEMP_SWEEP_GRACE_SECONDS:
                    await asyncio.to_thread(shutil.rmtree, entry, True)
                    _logger.info(f"Janitor removed stale temp dir: {entry}")
            except Exception as exc:
                _logger.warning(f"Temp sweep failed for {entry}: {exc}")

    async def _sweep_dangling_results(self) -> None:
        """Delete result artifacts whose task hash no longer exists in Redis."""
        prefix = f"{settings.MINIO_RESULT_PREFIX}/"
        try:
            keys = await self._storage.list_keys(prefix, limit=1000)
        except Exception as exc:
            _logger.warning(f"Results sweep failed to list objects: {exc}")
            return

        for key in keys:
            parts = key.split("/")
            if len(parts) < 2:
                continue
            task_id = parts[1]
            if task_id in self._active_ids:
                continue
            try:
                task = await self._task_service.get_task(task_id)
            except Exception:
                continue  # Redis hiccup - retry next sweep
            if task is None:
                await self._storage.delete_prefix(f"{prefix}{task_id}/")
                _logger.info(f"Janitor removed dangling result artifact: {key}")

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def _dispatch(
        self,
        endpoint: str,
        params: dict,
        file_path: Optional[str],
    ) -> dict:
        """Route to the correct ConversionService method based on endpoint name.

        Returns the result dict that will be stored in object storage.
        """
        cs = self._conversion_service

        # Parse common parameters
        enable_ocr = params.get("enable_ocr", False)
        output_type = OutputType(params.get("output_type", "markdown"))
        generate_picture_images = params.get("generate_picture_images", False)
        generate_table_images = params.get("generate_table_images", False)
        table_mode = params.get("table_mode")  # "fast" or "accurate" or None

        # Resolve image_mode
        image_mode_str = params.get("image_mode")
        image_mode: Optional[ImageRefMode] = None
        if image_mode_str:
            mode_map = {
                "embedded": ImageRefMode.EMBEDDED,
                "referenced": ImageRefMode.REFERENCED,
                "placeholder": ImageRefMode.PLACEHOLDER,
            }
            image_mode = mode_map.get(image_mode_str)

        # Build optional page range
        page_range = build_page_range(
            params.get("from_page"), params.get("to_page")
        )

        if endpoint == "convert":
            converter = await cs.initialize_converter(
                enable_ocr,
                generate_picture_images=generate_picture_images,
                table_mode=table_mode,
                generate_table_images=generate_table_images,
            )
            api_result = await cs.convert(
                file_path, output_type, page_range=page_range,
                image_mode=image_mode, converter=converter,
            )
            if api_result.is_error():
                raise RuntimeError(api_result.error_message)
            return api_result.data

        elif endpoint == "convert_n_chunk":
            max_tokens = int(params.get("max_tokens", 512))
            chunk_type = ChunkType(params.get("chunk_type", "hybrid"))
            ocr_langs_raw = params.get("ocr_langs", "id")
            ocr_langs = [lang.strip() for lang in ocr_langs_raw.split(",")]

            converter = await cs.initialize_converter(
                enable_ocr, ocr_langs,
                generate_picture_images=generate_picture_images,
                table_mode=table_mode,
                generate_table_images=generate_table_images,
            )
            api_result = await cs.convert_and_chunk(
                file_path, max_tokens, output_type, chunk_type,
                page_range=page_range, image_mode=image_mode,
                converter=converter,
            )
            if api_result.is_error():
                raise RuntimeError(api_result.error_message)
            return api_result.data

        else:
            raise ValueError(f"Unknown async endpoint: {endpoint}")
