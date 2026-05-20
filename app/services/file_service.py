"""File upload and management service."""

import os
import re
import time
import uuid
from datetime import datetime
from io import BytesIO
from typing import Dict, Optional, Set, Tuple

import aiofiles
import magic
from fastapi import HTTPException, UploadFile

from config import settings
from app.models.document_model import UploadSessionModel, UploadStatusEnum
from .base_service import BaseService


_RESUMABLE_EXPIRY_SECONDS: int = 7200  # 2h auto-cleanup for incomplete uploads


class FileService(BaseService):
    """Service for file upload, validation, and cleanup."""

    # Class-level dict to share upload sessions across request-scoped instances
    _upload_sessions: Dict[str, UploadSessionModel] = {}

    def __init__(self, logger) -> None:
        super().__init__(logger)
        self.upload_dir: str = settings.UPLOAD_DIR
        self.supported_formats: Set[str] = set(settings.SUPPORTED_FORMATS.split(','))
        os.makedirs(self.upload_dir, exist_ok=True)

    async def save_upload_file(self, file: UploadFile) -> str:
        """Save uploaded file and return file path."""
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
            is_supported = any(
                supported_format.endswith('/*') and file_type.startswith(supported_format[:-2])
                or file_type == supported_format
                for supported_format in self.supported_formats
            )

            if not is_supported:
                self.logger.warning(f"Unsupported file type: {file_type}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported file type: {file_type}. Supported: {self.supported_formats}"
                )

            # Generate safe filename
            safe_filename = self._get_safe_filename(file.filename)
            file_path = os.path.join(self.upload_dir, safe_filename)

            # Save file with size limit check
            total_written = 0
            async with aiofiles.open(file_path, 'wb') as f:
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

    def _get_safe_filename(self, filename: str) -> str:
        """Generate safe filename with timestamp to avoid collisions."""
        # Remove path separators and keep only filename
        name = os.path.basename(filename)
        # Replace unsafe characters
        name = re.sub(r'[^\w\.-]', '_', name)
        # Add timestamp to avoid collisions
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name, ext = os.path.splitext(name)
        return f"{name}_{timestamp}{ext}"

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
        is_supported = any(
            supported_format.endswith('/*') and file_type.startswith(supported_format[:-2])
            or file_type == supported_format
            for supported_format in self.supported_formats
        )

        if not is_supported:
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
        """Remove temporary file."""
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                self.logger.info(f"Cleaned up file: {file_path}")
        except Exception as e:
            self.logger.warning(f"Could not cleanup file {file_path}: {str(e)}")

    # ------------------------------------------------------------------
    # Resumable Upload Support
    # ------------------------------------------------------------------

    @classmethod
    def _prune_expired_sessions(cls) -> None:
        """Remove upload sessions that have expired."""
        now = time.time()
        expired = [
            uid for uid, sess in cls._upload_sessions.items()
            if now - sess.updated_at > _RESUMABLE_EXPIRY_SECONDS
        ]
        for uid in expired:
            session = cls._upload_sessions.pop(uid, None)
            if session and session.file_path and os.path.exists(session.file_path):
                try:
                    os.remove(session.file_path)
                except OSError:
                    pass

    def init_upload(
        self,
        filename: str,
        total_size: int,
        mime_type: Optional[str] = None
    ) -> UploadSessionModel:
        """Initialize a new resumable upload session."""
        # Prune stale sessions first
        self._prune_expired_sessions()

        upload_id = uuid.uuid4().hex[:16]
        safe_filename = self._get_safe_filename(filename)

        session = UploadSessionModel(
            upload_id=upload_id,
            filename=filename,
            safe_filename=safe_filename,
            total_size=total_size,
            mime_type=mime_type,
        )
        self._upload_sessions[upload_id] = session

        self.logger.info(f"Upload session initialized: {upload_id}", extra={
            "filename": filename,
            "total_size": total_size
        })
        return session

    async def append_upload(
        self,
        upload_id: str,
        chunk: bytes,
        content_range: Optional[str] = None
    ) -> UploadSessionModel:
        """Append a chunk to an existing upload session.

        If content_range is provided (e.g. "bytes 0-1023/4096"), the chunk
        is written at the correct offset for out-of-order delivery support.
        Otherwise the chunk is simply appended.
        """
        session = self._upload_sessions.get(upload_id)
        if not session:
            raise HTTPException(
                status_code=404,
                detail=f"Upload session not found: {upload_id}"
            )

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
                end_byte = int(match.group(2))
                total = int(match.group(3))
                # Validate total matches session
                if total != session.total_size:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Content-Range total {total} does not match session total {session.total_size}"
                    )

        # Create file on first chunk
        if not session.file_path:
            session.file_path = os.path.join(self.upload_dir, session.safe_filename)

        # Write chunk
        async with aiofiles.open(session.file_path, 'ab') as f:
            if start_byte is not None:
                # Seek to the specified position for resumable uploads
                await f.seek(start_byte)
            await f.write(chunk)

        # Update session state
        chunk_size = len(chunk)
        if start_byte is not None:
            # For range-based, track max received byte
            session.received_size = max(session.received_size, start_byte + chunk_size)
        else:
            session.received_size += chunk_size

        session.updated_at = time.time()

        # Clamp received_size to total_size
        if session.received_size > session.total_size:
            session.received_size = session.total_size

        # Check if upload is complete
        if session.is_complete:
            # Validate file type on completion
            try:
                async with aiofiles.open(session.file_path, 'rb') as f:
                    header = await f.read(1024)
                file_type = magic.from_buffer(header, mime=True)

                is_supported = any(
                    supported_format.endswith('/*') and file_type.startswith(supported_format[:-2])
                    or file_type == supported_format
                    for supported_format in self.supported_formats
                )
                if not is_supported:
                    session.status = UploadStatusEnum.FAILED
                    self.logger.warning(f"Resumable upload completed but unsupported type: {file_type}")
                    raise HTTPException(
                        status_code=400,
                        detail=f"Unsupported file type: {file_type}. Supported: {self.supported_formats}"
                    )

                session.mime_type = file_type
                session.status = UploadStatusEnum.COMPLETED
                self.logger.info(f"Upload session completed: {upload_id}", extra={
                    "filename": session.filename,
                    "total_size": session.total_size,
                    "file_type": file_type
                })
            except HTTPException:
                raise
            except Exception as e:
                session.status = UploadStatusEnum.FAILED
                self.logger.error(f"Upload validation failed: {str(e)}", exc_info=True)
                raise HTTPException(
                    status_code=500, detail=f"Upload validation failed: {str(e)}"
                )

        return session

    def get_upload_status(self, upload_id: str) -> Optional[UploadSessionModel]:
        """Get current status of an upload session."""
        self._prune_expired_sessions()
        return self._upload_sessions.get(upload_id)

    def get_upload_file_path(self, upload_id: str) -> Optional[str]:
        """Get file path for a completed upload session."""
        session = self._upload_sessions.get(upload_id)
        if not session:
            return None
        if session.status != UploadStatusEnum.COMPLETED:
            return None
        return session.file_path

    def remove_upload_session(self, upload_id: str) -> None:
        """Remove an upload session and its file."""
        session = self._upload_sessions.pop(upload_id, None)
        if session and session.file_path and os.path.exists(session.file_path):
            try:
                os.remove(session.file_path)
            except OSError as e:
                self.logger.warning(f"Could not cleanup upload file: {e}")