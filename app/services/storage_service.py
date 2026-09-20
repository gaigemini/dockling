"""Object storage service backed by MinIO with a local-disk fallback.

Durable artifacts (uploaded inputs and result JSON) live in object storage;
Redis only stores task state and object-key pointers. When
``settings.MINIO_ENABLED`` is False the service transparently stores objects
as files under ``TEMP_DIR/storage`` so local development and unit tests work
without a MinIO instance.

The MinIO SDK is synchronous; every SDK call is wrapped in ``asyncio.to_thread``
to avoid blocking the event loop.
"""

import asyncio
import io
import shutil
from datetime import timedelta
from pathlib import Path
from typing import Optional

from minio import Minio
from minio.commonconfig import Filter
from minio.error import S3Error
from minio.lifecycleconfig import Expiration, LifecycleConfig, Rule

from config import get_service_logger, settings
from app.services.base_service import BaseService

_storage_service: Optional["StorageService"] = None


def _normalize_key(object_key: str) -> str:
    """Normalize an object key into a safe relative path (local fallback)."""
    cleaned = object_key.replace("\\", "/").lstrip("/")
    parts = [p for p in cleaned.split("/") if p not in ("", ".", "..")]
    return "/".join(parts)


class StorageService(BaseService):
    """Store and retrieve task artifacts (MinIO or local-disk fallback)."""

    def __init__(self, logger=None, client: Optional[Minio] = None) -> None:
        super().__init__(logger)
        self.enabled: bool = settings.MINIO_ENABLED
        self.bucket: str = settings.MINIO_BUCKET
        self._local_root: Path = Path(settings.TEMP_DIR) / "storage"
        self._client: Optional[Minio] = client

        if self.enabled and self._client is None:
            self._client = Minio(
                settings.MINIO_ENDPOINT,
                access_key=settings.MINIO_ACCESS_KEY,
                secret_key=settings.MINIO_SECRET_KEY,
                secure=settings.MINIO_SECURE,
                region=settings.MINIO_REGION,
            )

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    async def ensure_bucket(self) -> None:
        """Create the configured bucket if it does not exist yet."""
        if not self.enabled:
            self._local_root.mkdir(parents=True, exist_ok=True)
            return

        def _ensure() -> None:
            if not self._client.bucket_exists(self.bucket):
                self._client.make_bucket(self.bucket, location=settings.MINIO_REGION)

        await asyncio.to_thread(_ensure)
        self.logger.info(f"MinIO bucket ready: {self.bucket}")

    async def ensure_result_lifecycle(self) -> None:
        """Apply the expiry lifecycle rule on the results/ prefix.

        This is the bucket-level safety net for ``TASK_RESULT_TTL`` (7 days);
        the janitor additionally sweeps dangling artifacts.
        """
        if not self.enabled:
            return
        prefix = f"{settings.MINIO_RESULT_PREFIX}/"
        try:
            rule = Rule(
                status="Enabled",
                rule_filter=Filter(prefix=prefix),
                rule_id="expire-results",
                expiration=Expiration(days=settings.MINIO_RESULT_TTL_DAYS),
            )
            await asyncio.to_thread(
                self._client.set_bucket_lifecycle,
                self.bucket,
                LifecycleConfig([rule]),
            )
            self.logger.info(
                f"MinIO lifecycle rule set: {prefix} expires after "
                f"{settings.MINIO_RESULT_TTL_DAYS} days"
            )
        except Exception as exc:
            # Non-fatal: the janitor still enforces retention.
            self.logger.warning(f"Could not set MinIO lifecycle rule: {exc}")

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    async def upload_file(
        self,
        local_path: str,
        object_key: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload a local file and return the normalized object key."""
        key = _normalize_key(object_key)
        if not self.enabled:
            dest = self._local_path(key)
            dest.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(shutil.copyfile, local_path, dest)
            return key

        await asyncio.to_thread(
            self._client.fput_object,
            self.bucket,
            key,
            local_path,
            content_type=content_type,
        )
        return key

    async def upload_bytes(
        self,
        object_key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload raw bytes and return the normalized object key."""
        key = _normalize_key(object_key)
        if not self.enabled:
            dest = self._local_path(key)
            dest.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(dest.write_bytes, data)
            return key

        await asyncio.to_thread(
            self._client.put_object,
            self.bucket,
            key,
            io.BytesIO(data),
            len(data),
            content_type=content_type,
        )
        return key

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    async def download_to_file(self, object_key: str, dest_path: str) -> str:
        """Download an object to a local file path."""
        key = _normalize_key(object_key)
        dest = Path(dest_path)
        await asyncio.to_thread(dest.parent.mkdir, parents=True, exist_ok=True)

        if not self.enabled:
            await asyncio.to_thread(shutil.copyfile, self._local_path(key), dest)
            return str(dest)

        await asyncio.to_thread(self._client.fget_object, self.bucket, key, str(dest))
        return str(dest)

    async def get_object_bytes(self, object_key: str) -> bytes:
        """Read a full object into memory."""
        key = _normalize_key(object_key)
        if not self.enabled:
            return await asyncio.to_thread(self._local_path(key).read_bytes)

        def _read() -> bytes:
            response = self._client.get_object(self.bucket, key)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()

        return await asyncio.to_thread(_read)

    # ------------------------------------------------------------------
    # Delete / inspect
    # ------------------------------------------------------------------

    async def delete_object(self, object_key: str) -> bool:
        """Delete a single object. Returns True when something was removed."""
        key = _normalize_key(object_key)
        if not self.enabled:
            path = self._local_path(key)
            if path.exists():
                await asyncio.to_thread(path.unlink)
                return True
            return False

        try:
            await asyncio.to_thread(self._client.remove_object, self.bucket, key)
            return True
        except S3Error as exc:
            if exc.code in ("NoSuchKey", "NoSuchObject", "NoSuchBucket"):
                return False
            raise

    async def delete_prefix(self, prefix: str) -> int:
        """Delete all objects under a prefix. Returns the number removed."""
        key_prefix = _normalize_key(prefix)
        if not self.enabled:
            target = self._local_path(key_prefix)
            if target.exists():
                await asyncio.to_thread(shutil.rmtree, target)
                return 1
            return 0

        def _delete() -> int:
            removed = 0
            for obj in self._client.list_objects(
                self.bucket, prefix=key_prefix, recursive=True
            ):
                self._client.remove_object(self.bucket, obj.object_name)
                removed += 1
            return removed

        return await asyncio.to_thread(_delete)

    async def object_exists(self, object_key: str) -> bool:
        """Check whether an object exists."""
        key = _normalize_key(object_key)
        if not self.enabled:
            return self._local_path(key).exists()
        try:
            await asyncio.to_thread(self._client.stat_object, self.bucket, key)
            return True
        except S3Error:
            return False

    async def list_keys(self, prefix: str, limit: int = 1000) -> list:
        """List object keys under a prefix (capped at ``limit``)."""
        key_prefix = _normalize_key(prefix)
        if not self.enabled:
            target = self._local_path(key_prefix)
            if not target.exists():
                return []
            if target.is_file():
                return [key_prefix]
            keys = []
            for path in sorted(target.rglob("*")):
                if path.is_file():
                    keys.append(str(path.relative_to(self._local_root)).replace("\\", "/"))
                    if len(keys) >= limit:
                        break
            return keys

        def _list() -> list:
            keys = []
            for obj in self._client.list_objects(
                self.bucket, prefix=key_prefix, recursive=True
            ):
                keys.append(obj.object_name)
                if len(keys) >= limit:
                    break
            return keys

        return await asyncio.to_thread(_list)

    async def presign_get_url(self, object_key: str) -> Optional[str]:
        """Return a presigned GET URL, or None in local fallback mode."""
        if not self.enabled:
            return None
        key = _normalize_key(object_key)
        try:
            return await asyncio.to_thread(
                self._client.presigned_get_object,
                self.bucket,
                key,
                expires=timedelta(seconds=settings.MINIO_PRESIGN_EXPIRY),
            )
        except S3Error as exc:
            self.logger.warning(f"Presign failed for {key}: {exc}")
            return None

    async def health(self) -> bool:
        """Return True when the backing store is reachable."""
        if not self.enabled:
            return True
        try:
            return bool(await asyncio.to_thread(self._client.bucket_exists, self.bucket))
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _local_path(self, key: str) -> Path:
        return self._local_root / key


# ----------------------------------------------------------------------
# Module-level singleton accessors (mirrors app.utils.redis_client pattern)
# ----------------------------------------------------------------------


def init_storage_service(logger=None) -> "StorageService":
    """Initialize the process-wide StorageService singleton."""
    global _storage_service
    if _storage_service is None:
        _storage_service = StorageService(logger or get_service_logger("storage"))
    return _storage_service


def get_storage_service() -> "StorageService":
    """Return the shared StorageService.

    Raises:
        RuntimeError: If ``init_storage_service`` has not been called yet.
    """
    if _storage_service is None:
        raise RuntimeError(
            "StorageService not initialized. Call init_storage_service() first."
        )
    return _storage_service


def set_storage_service(service: Optional["StorageService"]) -> None:
    """Override the singleton (used in tests)."""
    global _storage_service
    _storage_service = service
