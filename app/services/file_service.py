"""File upload and management service.

Uploads are validated (size + magic bytes) and stored in object storage
(MinIO, or the local-disk fallback under ``TEMP_DIR/storage``). Local disk is
used only as scratch space while an upload is being assembled. Resumable
upload sessions are persisted in Redis (``upload:{upload_id}``, 2h TTL) and
bound to the authenticated user.
"""

import os
import re
import time
import uuid
from io import BytesIO
from pathlib import Path
from typing import Dict, Optional, Set, Tuple

import aiofiles
import magic
from fastapi import HTTPException, UploadFile

from config import settings
from app.models.document_model import UploadSessionModel, UploadStatusEnum
from app.services.storage_service import get_storage_service
from app.utils.redis_client import get_redis
from .base_service import BaseService


_UPLOAD_SESSION_KEY_PREFIX = "upload:"
_SESSION_SCRATCH_SUBDIR = "sessions"


class FileService(BaseService):
    """Service for file upload, validation, and cleanup."""

    def __init__(self, logger) -> None:
        super().__init__(logger)
        self.temp_dir: str = settings.TEMP_DIR
        self.supported_formats: Set[str] = set(settings.SUPPORTED_FORMATS.split(','))
        os.makedirs(self.temp_dir, exist_ok=True)
        os.makedirs(os.path.join(self.temp_dir, _SESSION_SCRATCH_SUBDIR), exist_ok=True)

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    def _get_safe_filename(self, filename: str) -> str:
        """Generate a safe, collision-free filename (uuid suffix)."""
        # Remove path separators and keep only filename
        name = os.path.basename(filename)
        # Replace unsafe characters
        name = re.sub(r'[^\w\.-]', '_', name)
        stem, ext = os.path.splitext(name)
        return f"{stem}_{uuid.uuid4().hex[:8]}{ext}"

    def _check_supported_type(self, file_type: str) -> bool:
        """Return True when the detected MIME type is supported."""
        return any(
            supported_format.endswith('/*') and file_type.startswith(supported_format[:-2])
            or file_type == supported_format
            for supported_format in self.supported_formats
        )

    # ------------------------------------------------------------------
    # Direct uploads
    # ------------------------------------------------------------------

    async def save_upload_file(self, file: UploadFile) -> str:
        """Validate an upload, save it to local scratch, and return its path."""
        self.logger.info(f"Processing file upload: {file.filename}")

        try:
            # Validate file size via Content-Length header first (fast check)
            if file.size is not None and file.size > settings.MAX_FILE_SIZE:
                self.logger.warning(f"File too large (Content-Length): {file.size} bytes")
                raise HTTPException(
                    status_code=413,
                    detail=f"File too large. Maximum size is {settings.MAX_FILE_SIZE // (1024*1024)}MB"
                )

            # Validate file type (read first 1024 bytes for magic bytes)
            content = await file.read(1024)
            file_type = magic.from_buffer(content, mime=True)

            # Check if file type is supported
            if not self._check_supported_type(file_type):
                self.logger.warning(f"Unsupported file type: {file_type}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported file type: {file_type}. Supported: {self.supported_formats}"
                )

            # Generate safe filename
            safe_filename = self._get_safe_filename(file.filename)
            file_path = os.path.join(self.temp_dir, safe_filename)

            # Save file with size limit check
            # The first 1024 bytes were already consumed for MIME validation,
            # so we must write them back before reading the remaining chunks.
            total_written = len(content)
            async with aiofiles.open(file_path, 'wb') as f:
                await f.write(content)
                while chunk := await file.read(settings.UPLOAD_CHUNK_SIZE):
                    total_written += len(chunk)
                    if total_written > settings.MAX_FILE_SIZE:
                        self.logger.warning(f"File exceeded size limit during upload: {total_written} bytes")
                        # Clean up partial file
                        f.close()
                        os.remove(file_path)
                        raise HTTPException(
                            status_code=413,
                            detail=f"File exceeds maximum size of {settings.MAX_FILE_SIZE // (1024*1024)}MB"
                        )
                    await f.write(chunk)

            self.logger.info(f"File saved successfully: {safe_filename}", extra={
                "file_size": total_written,
                "file_type": file_type
            })
            return file_path

        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error saving file: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=500, detail=f"Error saving file: {str(e)}")

    async def store_upload(self, file: UploadFile) -> Tuple[str, str]:
        """Validate an upload and store it in object storage.

        Returns:
            ``(object_key, safe_filename)``. The local scratch copy is removed.
        """
        file_path = await self.save_upload_file(file)
        try:
            try:
                content_type = magic.from_file(file_path, mime=True)
            except Exception:
                content_type = "application/octet-stream"

            object_key = (
                f"{settings.MINIO_UPLOAD_PREFIX}/{uuid.uuid4().hex}/{Path(file_path).name}"
            )
            storage = get_storage_service()
            await storage.upload_file(file_path, object_key, content_type=content_type)
        finally:
            self.cleanup_file(file_path)

        self.logger.info(f"Upload stored in object storage: {object_key}")
        return object_key, Path(file_path).name

    async def validate_and_read_stream(self, file: UploadFile) -> Tuple[BytesIO, str, str]:
        """Validate file type/size and read content into BytesIO (streaming, no disk write)."""
        self.logger.info(f"Validating file stream: {file.filename}")

        # Validate file size via Content-Length header first (fast check)
        if file.size is not None and file.size > settings.MAX_FILE_SIZE:
            self.logger.warning(f"File too large (Content-Length): {file.size} bytes")
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Maximum size is {settings.MAX_FILE_SIZE // (1024*1024)}MB"
            )

        # Read first chunk for magic bytes validation
        header = await file.read(1024)
        file_type = magic.from_buffer(header, mime=True)

        # Check if file type is supported
        if not self._check_supported_type(file_type):
            self.logger.warning(f"Unsupported file type: {file_type}")
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {file_type}. Supported: {self.supported_formats}"
            )

        # Stream entire file into BytesIO with size limit check
        buffer = BytesIO()
        buffer.write(header)
        total_written = len(header)

        while chunk := await file.read(settings.UPLOAD_CHUNK_SIZE):
            total_written += len(chunk)
            if total_written > settings.MAX_FILE_SIZE:
                self.logger.warning(f"File exceeded size limit during streaming: {total_written} bytes")
                raise HTTPException(
                    status_code=413,
                    detail=f"File exceeds maximum size of {settings.MAX_FILE_SIZE // (1024*1024)}MB"
                )
            buffer.write(chunk)

        buffer.seek(0)
        safe_filename = self._get_safe_filename(file.filename)

        self.logger.info(f"File validated and read into stream: {safe_filename}", extra={
            "file_size": total_written,
            "file_type": file_type
        })

        return buffer, safe_filename, file_type

    def cleanup_file(self, file_path: str) -> None:
        """Remove a local scratch file."""
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
                self.logger.info(f"Cleaned up file: {file_path}")
        except Exception as e:
            self.logger.warning(f"Could not cleanup file {file_path}: {str(e)}")

    # ------------------------------------------------------------------
    # Resumable upload support (sessions persisted in Redis)
    # ------------------------------------------------------------------

    @staticmethod
    def _session_key(upload_id: str) -> str:
        return f"{_UPLOAD_SESSION_KEY_PREFIX}{upload_id}"

    @staticmethod
    def _session_to_mapping(session: UploadSessionModel) -> Dict[str, str]:
        return {
            "upload_id": session.upload_id,
            "filename": session.filename,
            "safe_filename": session.safe_filename,
            "file_path": session.file_path or "",
            "object_key": session.object_key or "",
            "total_size": str(session.total_size),
            "received_size": str(session.received_size),
            "status": session.status.value,
            "mime_type": session.mime_type or "",
            "user_id": session.user_id or "",
            "created_at": str(session.created_at),
            "updated_at": str(session.updated_at),
        }

    @staticmethod
    def _mapping_to_session(raw: Dict[str, str]) -> UploadSessionModel:
        return UploadSessionModel(
            upload_id=raw["upload_id"],
            filename=raw["filename"],
            safe_filename=raw["safe_filename"],
            file_path=raw.get("file_path") or "",
            object_key=raw.get("object_key") or "",
            total_size=int(raw["total_size"]),
            received_size=int(raw.get("received_size", "0") or 0),
            status=UploadStatusEnum(raw.get("status", UploadStatusEnum.IN_PROGRESS.value)),
            mime_type=raw.get("mime_type") or None,
            user_id=raw.get("user_id") or "",
            created_at=float(raw.get("created_at", 0) or 0),
            updated_at=float(raw.get("updated_at", 0) or 0),
        )

    async def _get_session(self, upload_id: str) -> Optional[UploadSessionModel]:
        """Load an upload session from Redis."""
        redis = get_redis()
        raw = await redis.hgetall(self._session_key(upload_id))
        if not raw:
            return None
        return self._mapping_to_session(raw)

    async def _save_session(self, session: UploadSessionModel) -> None:
        """Persist a session to Redis and refresh its TTL."""
        session.updated_at = time.time()
        redis = get_redis()
        key = self._session_key(session.upload_id)
        await redis.hset(key, mapping=self._session_to_mapping(session))
        await redis.expire(key, settings.UPLOAD_SESSION_TTL)

    def _check_ownership(self, session: UploadSessionModel, user_id: Optional[str]) -> None:
        """Reject access to sessions owned by a different user."""
        if user_id and session.user_id and session.user_id != user_id:
            self.logger.warning(
                f"Upload session {session.upload_id} accessed by wrong user: "
                f"{user_id} != {session.user_id}"
            )
            raise HTTPException(
                status_code=403,
                detail="Upload session belongs to a different user",
            )

    async def init_upload(
        self,
        filename: str,
        total_size: int,
        mime_type: Optional[str] = None,
        user_id: str = "",
    ) -> UploadSessionModel:
        """Initialize a new resumable upload session."""
        upload_id = uuid.uuid4().hex[:16]
        safe_filename = self._get_safe_filename(filename)

        session = UploadSessionModel(
            upload_id=upload_id,
            filename=filename,
            safe_filename=safe_filename,
            total_size=total_size,
            mime_type=mime_type,
            user_id=user_id,
        )
        await self._save_session(session)

        self.logger.info(f"Upload session initialized: {upload_id}", extra={
            "filename": filename,
            "total_size": total_size,
            "user_id": user_id,
        })
        return session

    async def append_upload(
        self,
        upload_id: str,
        chunk: bytes,
        content_range: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> UploadSessionModel:
        """Append a chunk to an existing upload session.

        If content_range is provided (e.g. "bytes 0-1023/4096"), the chunk
        is written at the correct offset for out-of-order delivery support.
        Otherwise the chunk is simply appended.
        """
        session = await self._get_session(upload_id)
        if not session:
            raise HTTPException(
                status_code=404,
                detail=f"Upload session not found: {upload_id}"
            )

        self._check_ownership(session, user_id)

        if session.status != UploadStatusEnum.IN_PROGRESS:
            raise HTTPException(
                status_code=400,
                detail=f"Upload session {upload_id} is already {session.status.value}"
            )

        # Parse Content-Range if provided
        start_byte = None
        if content_range:
            match = re.match(r'bytes\s+(\d+)-(\d+)/(\d+)', content_range)
            if match:
                start_byte = int(match.group(1))
                total = int(match.group(3))
                # Validate total matches session
                if total != session.total_size:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Content-Range total {total} does not match session total {session.total_size}"
                    )

        # Resolve local scratch path on first chunk
        if not session.file_path:
            session.file_path = os.path.join(
                self.temp_dir, _SESSION_SCRATCH_SUBDIR, upload_id, session.safe_filename
            )

        path = Path(session.file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.touch()

        # Write chunk. NOTE: 'ab' (O_APPEND) ignores seeks on POSIX, which
        # silently corrupts out-of-order uploads - always use 'r+b' + seek.
        async with aiofiles.open(path, 'r+b') as f:
            if start_byte is not None:
                await f.seek(start_byte)
            else:
                await f.seek(0, os.SEEK_END)
            await f.write(chunk)

        # Update session state
        chunk_size = len(chunk)
        if start_byte is not None:
            # For range-based, track max received byte
            session.received_size = max(session.received_size, start_byte + chunk_size)
        else:
            session.received_size += chunk_size

        # Clamp received_size to total_size
        if session.received_size > session.total_size:
            session.received_size = session.total_size

        # Check if upload is complete
        if session.is_complete:
            try:
                async with aiofiles.open(session.file_path, 'rb') as f:
                    header = await f.read(1024)
                file_type = magic.from_buffer(header, mime=True)

                if not self._check_supported_type(file_type):
                    session.status = UploadStatusEnum.FAILED
                    await self._save_session(session)
                    self.logger.warning(f"Resumable upload completed but unsupported type: {file_type}")
                    raise HTTPException(
                        status_code=400,
                        detail=f"Unsupported file type: {file_type}. Supported: {self.supported_formats}"
                    )

                session.mime_type = file_type

                # Move the assembled file to object storage and drop scratch.
                object_key = (
                    f"{settings.MINIO_UPLOAD_PREFIX}/{upload_id}/{session.safe_filename}"
                )
                storage = get_storage_service()
                await storage.upload_file(session.file_path, object_key, content_type=file_type)
                self.cleanup_file(session.file_path)
                try:
                    path.parent.rmdir()  # remove now-empty session scratch dir
                except OSError:
                    pass
                session.file_path = ""
                session.object_key = object_key
                session.status = UploadStatusEnum.COMPLETED

                self.logger.info(f"Upload session completed: {upload_id}", extra={
                    "filename": session.filename,
                    "total_size": session.total_size,
                    "file_type": file_type,
                    "object_key": object_key,
                })
            except HTTPException:
                raise
            except Exception as e:
                session.status = UploadStatusEnum.FAILED
                await self._save_session(session)
                self.logger.error(f"Upload validation failed: {str(e)}", exc_info=True)
                raise HTTPException(
                    status_code=500, detail=f"Upload validation failed: {str(e)}"
                )

        await self._save_session(session)
        return session

    async def get_upload_status(self, upload_id: str) -> Optional[UploadSessionModel]:
        """Get current status of an upload session."""
        return await self._get_session(upload_id)

    async def get_upload_object_key(self, upload_id: str) -> Optional[str]:
        """Get the object storage key for a completed upload session."""
        session = await self._get_session(upload_id)
        if not session or session.status != UploadStatusEnum.COMPLETED:
            return None
        return session.object_key or None

    async def remove_upload_session(self, upload_id: str) -> None:
        """Remove an upload session, its scratch file, and (best-effort) object."""
        session = await self._get_session(upload_id)
        if session:
            if session.file_path and os.path.exists(session.file_path):
                self.cleanup_file(session.file_path)
                try:
                    Path(session.file_path).parent.rmdir()
                except OSError:
                    pass
            if session.object_key:
                try:
                    await get_storage_service().delete_object(session.object_key)
                except Exception as exc:
                    self.logger.warning(
                        f"Could not delete object {session.object_key}: {exc}"
                    )
        redis = get_redis()
        await redis.delete(self._session_key(upload_id))
