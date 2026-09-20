"""Document processing endpoints with streaming and resumable upload support."""

import asyncio
import os
import shutil
import time
from io import BytesIO
from typing import Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import JSONResponse
from pydantic import AnyHttpUrl, TypeAdapter, ValidationError

from docling_core.types.doc.base import ImageRefMode

from app.dependencies.auth import get_current_user
from app.dependencies.logger import get_request_logger_dep
from app.models.api_response import ApiResponse
from app.models.common import CurrentUserModel
from app.models.document_model import (
    ChunkTextRequestModel,
    ChunkType,
    ConvertTextRequestModel,
    ImageMode,
    OutputType,
    UploadStatusEnum,
)
from app.models.task_model import TaskSubmitResponse, TaskStatus
from app.services.file_service import FileService
from app.services.storage_service import get_storage_service
from app.utils.params import build_page_range as _build_page_range
from app.utils.params import parse_bool as _parse_bool
from config import settings

router = APIRouter(
    prefix="/api/v1",
    tags=["documents"],
    dependencies=[Depends(get_current_user)]
)

# Endpoint-level limiter: reject with 429 when all conversion slots are busy.
_conversion_semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_CONVERSIONS)
_callback_url_adapter = TypeAdapter(AnyHttpUrl)


def _validate_callback_url(url: Optional[str]) -> Optional[str]:
    """Validate an optional webhook callback URL (absolute http/https)."""
    if not url:
        return None
    try:
        _callback_url_adapter.validate_python(url)
    except ValidationError:
        raise HTTPException(
            status_code=422,
            detail="Invalid callback_url: an absolute http(s) URL is required",
        )
    return url


async def _acquire_conversion_slot() -> None:
    """Raise 429 when every conversion slot is currently busy."""
    if _conversion_semaphore.locked():
        raise HTTPException(
            status_code=429,
            detail="Server is busy processing other documents. Please retry shortly.",
        )


def _resolve_image_mode(image_mode: Optional[ImageMode]) -> Optional[ImageRefMode]:
    """Convert API ImageMode enum to Docling ImageRefMode.

    Returns None if not provided (service will use its default).
    """
    if image_mode is None:
        return None
    mapping = {
        ImageMode.EMBEDDED: ImageRefMode.EMBEDDED,
        ImageMode.REFERENCED: ImageRefMode.REFERENCED,
        ImageMode.PLACEHOLDER: ImageRefMode.PLACEHOLDER,
    }
    return mapping.get(image_mode)


def _should_use_stream(file_size: Optional[int], use_stream: Optional[bool]) -> bool:
    """Decide whether to use in-memory streaming or file-based conversion.

    Priority:
    1. use_stream explicitly provided → honour it
    2. use_stream is None → auto-detect based on file size vs MAX_STREAM_SIZE
    """
    if use_stream is not None:
        return use_stream
    # Auto: stream only if file fits in max stream size
    if file_size is not None:
        return file_size <= settings.MAX_STREAM_SIZE
    # No file size info → safe fallback to file-based
    return False


async def _cleanup_dir(path: str) -> None:
    """Remove a scratch directory (best-effort, used as background task)."""
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass


async def _prepare_file(
    file: UploadFile,
    upload_id: Optional[str],
    background_tasks: BackgroundTasks,
    logger,
    user: Optional[CurrentUserModel] = None,
) -> tuple:
    """Prepare file for conversion: stream BytesIO or local scratch path.

    Returns (buffer_or_path, filename, is_streaming)
    - If streaming: (BytesIO, filename, True)
    - If file-based: (file_path, filename, False)
    """
    file_service = FileService(logger)

    # If upload_id is provided, use a previously uploaded file
    if upload_id:
        session = await file_service.get_upload_status(upload_id)
        if not session:
            raise HTTPException(
                status_code=404,
                detail=f"Upload session not found: {upload_id}"
            )
        if user and session.user_id and session.user_id != user.id:
            raise HTTPException(
                status_code=403,
                detail="Upload session belongs to a different user",
            )
        if session.status != UploadStatusEnum.COMPLETED:
            raise HTTPException(
                status_code=409,
                detail=f"Upload session is not completed yet ({session.status.value})",
            )
        if not session.object_key:
            raise HTTPException(
                status_code=404,
                detail=f"Upload session has no stored file: {upload_id}"
            )

        # Input lives in object storage: download to local scratch for Docling
        scratch_dir = os.path.join(settings.TEMP_DIR, f"session-{upload_id}")
        local_path = os.path.join(scratch_dir, session.safe_filename)
        await get_storage_service().download_to_file(session.object_key, local_path)
        logger.info(f"Using pre-uploaded file for conversion: {upload_id}", extra={
            "filename": session.filename,
            "object_key": session.object_key,
        })
        # One-shot consumption: clean scratch + session (+ object) afterwards
        background_tasks.add_task(_cleanup_dir, scratch_dir)
        background_tasks.add_task(file_service.remove_upload_session, upload_id)
        return local_path, session.filename, False

    # Direct file upload
    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    use_stream = _should_use_stream(file.size, None)

    if use_stream:
        # In-memory streaming (no disk write)
        buffer, filename, _ = await file_service.validate_and_read_stream(file)
        logger.info(f"Using streaming conversion: {filename}")
        return buffer, filename, True
    else:
        # Save to local scratch first (for large files)
        file_path = await file_service.save_upload_file(file)
        filename = file.filename
        background_tasks.add_task(file_service.cleanup_file, file_path)
        logger.info(f"Using file-based conversion: {filename}")
        return file_path, filename, False


# ------------------------------------------------------------------
# Existing Conversion Endpoints
# ------------------------------------------------------------------


@router.post("/convert", response_model=ApiResponse)
async def convert(
    background_tasks: BackgroundTasks,
    request: Request,
    file: UploadFile = File(None, description="Document file to process"),
    upload_id: Optional[str] = Form(None, description="Use a previously uploaded file via upload session ID"),
    use_stream: Optional[bool] = Form(None, description="Force streaming (true) or file-based (false). Auto if None."),
    enable_ocr: str = Form("false"),
    output_type: OutputType = OutputType.MARKDOWN,
    generate_picture_images: str = Form("false", description="Extract and embed images from PDF (true/false)"),
    generate_table_images: str = Form("false", description="Generate table images alongside structure (true/false)"),
    table_mode: Optional[str] = Form(None, pattern="^(fast|accurate)$", description="TableFormer mode: 'fast' or 'accurate' (default)"),
    image_mode: Optional[ImageMode] = Form(None, description="Image reference mode: embedded, referenced, placeholder"),
    from_page: Optional[int] = Form(None, ge=1, description="Start page (1-based, inclusive)"),
    to_page: Optional[int] = Form(None, ge=1, description="End page (1-based, inclusive)"),
    user: CurrentUserModel = Depends(get_current_user),
    logger=Depends(get_request_logger_dep)
) -> ApiResponse:
    """Process uploaded document with Docling - supports streaming and resumable upload.

    Use from_page and to_page to convert only a specific page range (1-based, inclusive).
    """
    start_time = time.time()
    enable_ocr_bool = _parse_bool(enable_ocr)
    generate_images_bool = _parse_bool(generate_picture_images)
    generate_table_images_bool = _parse_bool(generate_table_images)

    logger.info(f"Processing document: {file.filename if file else upload_id}", extra={
        "enable_ocr": enable_ocr_bool,
        "output_type": output_type,
        "use_stream": use_stream,
        "upload_id": upload_id,
        "generate_picture_images": generate_images_bool,
        "generate_table_images": generate_table_images_bool,
        "table_mode": table_mode,
        "image_mode": image_mode,
        "from_page": from_page,
        "to_page": to_page,
        "client_ip": request.client.host if request.client else "unknown"
    })

    try:
        # Prepare file source (stream or file path)
        source, filename, is_streaming = await _prepare_file(
            file, upload_id, background_tasks, logger, user
        )

        # Get singleton conversion service from app state
        cs = request.app.state.conversion_service

        # Initialize (or reuse cached) converter for these settings
        converter = await cs.initialize_converter(
            enable_ocr_bool,
            logger=logger,
            generate_picture_images=generate_images_bool,
            table_mode=table_mode,
            generate_table_images=generate_table_images_bool
        )

        # Process document (bounded by the global concurrency limiter)
        page_range = _build_page_range(from_page, to_page)
        resolved_image_mode = _resolve_image_mode(image_mode)
        await _acquire_conversion_slot()
        async with _conversion_semaphore:
            if is_streaming:
                result = await cs.convert_stream(
                    source, filename, output_type,
                    page_range=page_range, image_mode=resolved_image_mode,
                    logger=logger, converter=converter,
                )
            else:
                result = await cs.convert(
                    source, output_type,
                    page_range=page_range, image_mode=resolved_image_mode,
                    logger=logger, converter=converter,
                )

        if result.is_success():
            result.data["processing_time"] = time.time() - start_time
            result.data["streaming_used"] = is_streaming

        logger.info("Document processing completed", extra={
            "success": result.is_success(),
            "streaming": is_streaming,
            "total_processing_time": time.time() - start_time
        })

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in process_document: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Document processing failed")


@router.post("/convert_n_chunk", response_model=ApiResponse)
async def convert_n_chunk(
    background_tasks: BackgroundTasks,
    request: Request,
    file: UploadFile = File(None, description="Document file to process"),
    upload_id: Optional[str] = Form(None, description="Use a previously uploaded file via upload session ID"),
    use_stream: Optional[bool] = Form(None, description="Force streaming (true) or file-based (false). Auto if None."),
    enable_ocr: str = Form("false"),
    ocr_langs: str = Form("id"),
    max_tokens: int = Form(512),
    output_type: OutputType = OutputType.MARKDOWN,
    chunk_type: ChunkType = ChunkType.HYBRID,
    generate_picture_images: str = Form("false", description="Extract and embed images from PDF (true/false)"),
    generate_table_images: str = Form("false", description="Generate table images alongside structure (true/false)"),
    table_mode: Optional[str] = Form(None, pattern="^(fast|accurate)$", description="TableFormer mode: 'fast' or 'accurate' (default)"),
    image_mode: Optional[ImageMode] = Form(None, description="Image reference mode: embedded, referenced, placeholder"),
    from_page: Optional[int] = Form(None, ge=1, description="Start page (1-based, inclusive)"),
    to_page: Optional[int] = Form(None, ge=1, description="End page (1-based, inclusive)"),
    user: CurrentUserModel = Depends(get_current_user),
    logger=Depends(get_request_logger_dep)
) -> ApiResponse:
    """Convert and chunk document - supports streaming and resumable upload.

    Use from_page and to_page to convert only a specific page range (1-based, inclusive).
    """
    start_time = time.time()
    enable_ocr_bool = _parse_bool(enable_ocr)
    generate_images_bool = _parse_bool(generate_picture_images)
    generate_table_images_bool = _parse_bool(generate_table_images)
    ocr_langs_list = [lang.strip() for lang in ocr_langs.split(",")]

    logger.info(f"Processing document with chunking: {file.filename if file else upload_id}", extra={
        "enable_ocr": enable_ocr_bool,
        "max_tokens": max_tokens,
        "chunk_type": chunk_type,
        "use_stream": use_stream,
        "upload_id": upload_id,
        "generate_picture_images": generate_images_bool,
        "generate_table_images": generate_table_images_bool,
        "table_mode": table_mode,
        "image_mode": image_mode,
        "from_page": from_page,
        "to_page": to_page,
        "client_ip": request.client.host if request.client else "unknown"
    })

    try:
        # Prepare file source (stream or file path)
        source, filename, is_streaming = await _prepare_file(
            file, upload_id, background_tasks, logger, user
        )

        # Get singleton conversion service from app state
        cs = request.app.state.conversion_service

        # Initialize (or reuse cached) converter for these settings
        converter = await cs.initialize_converter(
            enable_ocr_bool, ocr_langs_list, logger=logger,
            generate_picture_images=generate_images_bool,
            table_mode=table_mode,
            generate_table_images=generate_table_images_bool
        )

        # Process document with chunking (bounded by the concurrency limiter)
        page_range = _build_page_range(from_page, to_page)
        resolved_image_mode = _resolve_image_mode(image_mode)
        await _acquire_conversion_slot()
        async with _conversion_semaphore:
            if is_streaming:
                result = await cs.convert_and_chunk_stream(
                    source, filename, max_tokens, output_type, chunk_type,
                    page_range=page_range, image_mode=resolved_image_mode,
                    logger=logger, converter=converter,
                )
            else:
                result = await cs.convert_and_chunk(
                    source, max_tokens, output_type, chunk_type,
                    page_range=page_range, image_mode=resolved_image_mode,
                    logger=logger, converter=converter,
                )

        if result.is_success():
            result.data["processing_time"] = time.time() - start_time
            result.data["streaming_used"] = is_streaming

        logger.info("Document conversion and chunking completed", extra={
            "success": result.is_success(),
            "streaming": is_streaming,
            "total_chunks": result.data.get("total_chunks", 0) if result.data else 0,
            "total_processing_time": time.time() - start_time
        })

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in convert_n_chunk: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Document conversion failed")


# ------------------------------------------------------------------
# Text-based Conversion Endpoints (no file upload required)
# ------------------------------------------------------------------


@router.post("/convert_text", response_model=ApiResponse)
async def convert_text(
    request: Request,
    body: ConvertTextRequestModel,
    logger=Depends(get_request_logger_dep)
) -> ApiResponse:
    """Convert raw markdown/text content without file upload.

    Client sends content as a JSON body. The content is wrapped in a
    BytesIO stream and processed by Docling as an in-memory document.
    """
    start_time = time.time()

    logger.info(f"Processing text content: {body.filename}", extra={
        "content_length": len(body.content),
        "output_type": body.output_type,
        "generate_picture_images": body.generate_picture_images,
        "generate_table_images": body.generate_table_images,
        "table_mode": body.table_mode,
        "image_mode": body.image_mode,
        "from_page": body.from_page,
        "to_page": body.to_page,
        "client_ip": request.client.host if request.client else "unknown"
    })

    try:
        # Wrap content in BytesIO for stream-based conversion
        buffer = BytesIO(body.content.encode("utf-8"))
        filename = body.filename or "document.md"

        cs = request.app.state.conversion_service
        converter = await cs.initialize_converter(
            False, logger=logger,
            generate_picture_images=body.generate_picture_images,
            table_mode=body.table_mode,
            generate_table_images=body.generate_table_images
        )

        await _acquire_conversion_slot()
        async with _conversion_semaphore:
            result = await cs.convert_stream(
                buffer, filename, body.output_type,
                page_range=_build_page_range(body.from_page, body.to_page),
                image_mode=_resolve_image_mode(body.image_mode),
                logger=logger, converter=converter,
            )

        if result.is_success():
            result.data["processing_time"] = time.time() - start_time

        logger.info("Text content processing completed", extra={
            "success": result.is_success(),
            "total_processing_time": time.time() - start_time
        })

        return result

    except Exception as e:
        logger.error(f"Unexpected error in convert_text: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Text conversion failed")


@router.post("/chunk_text", response_model=ApiResponse)
async def chunk_text(
    request: Request,
    body: ChunkTextRequestModel,
    logger=Depends(get_request_logger_dep)
) -> ApiResponse:
    """Convert and chunk raw markdown/text content without file upload.

    Client sends content as a JSON body (e.g. read from a database).
    The content is wrapped in a BytesIO stream and processed by Docling
    — no physical file is required.
    """
    start_time = time.time()

    logger.info(f"Processing text content with chunking: {body.filename}", extra={
        "content_length": len(body.content),
        "max_tokens": body.max_tokens,
        "chunk_type": body.chunk_type,
        "output_type": body.output_type,
        "generate_picture_images": body.generate_picture_images,
        "generate_table_images": body.generate_table_images,
        "table_mode": body.table_mode,
        "image_mode": body.image_mode,
        "from_page": body.from_page,
        "to_page": body.to_page,
        "client_ip": request.client.host if request.client else "unknown"
    })

    try:
        # Wrap content in BytesIO for stream-based conversion
        buffer = BytesIO(body.content.encode("utf-8"))
        filename = body.filename or "document.md"

        cs = request.app.state.conversion_service
        converter = await cs.initialize_converter(
            False, logger=logger,
            generate_picture_images=body.generate_picture_images,
            table_mode=body.table_mode,
            generate_table_images=body.generate_table_images
        )

        await _acquire_conversion_slot()
        async with _conversion_semaphore:
            result = await cs.convert_and_chunk_stream(
                buffer, filename, body.max_tokens, body.output_type, body.chunk_type,
                page_range=_build_page_range(body.from_page, body.to_page),
                image_mode=_resolve_image_mode(body.image_mode),
                logger=logger, converter=converter,
            )

        if result.is_success():
            result.data["processing_time"] = time.time() - start_time

        logger.info("Text content chunking completed", extra={
            "success": result.is_success(),
            "total_chunks": result.data.get("total_chunks", 0) if result.data else 0,
            "total_processing_time": time.time() - start_time
        })

        return result

    except Exception as e:
        logger.error(f"Unexpected error in chunk_text: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Text chunking failed")


# ------------------------------------------------------------------
# Resumable Upload Endpoints
# ------------------------------------------------------------------


@router.post("/upload/init", response_model=ApiResponse)
async def upload_init(
    request: Request,
    filename: str = Form(..., description="Original file name"),
    total_size: int = Form(..., ge=1, description="Total file size in bytes"),
    mime_type: Optional[str] = Form(None, description="MIME type of the file"),
    user: CurrentUserModel = Depends(get_current_user),
    logger=Depends(get_request_logger_dep)
) -> ApiResponse:
    """Initiate a resumable upload session."""
    logger.info(f"Initializing resumable upload: {filename}", extra={
        "total_size": total_size,
        "client_ip": request.client.host if request.client else "unknown"
    })

    try:
        if total_size > settings.MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Maximum size is {settings.MAX_FILE_SIZE // (1024*1024)}MB"
            )

        file_service = FileService(logger)
        session = await file_service.init_upload(
            filename, total_size, mime_type, user_id=user.id
        )

        return ApiResponse.success(data={
            "upload_id": session.upload_id,
            "filename": session.filename,
            "total_size": session.total_size,
            "received_size": session.received_size,
            "status": session.status.value,
            "progress": session.progress,
            "message": "Upload session initialized. Send chunks via PUT /upload/{upload_id}"
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload init error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Upload initiation failed")


@router.put("/upload/{upload_id}", response_model=ApiResponse)
async def upload_chunk(
    upload_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    user: CurrentUserModel = Depends(get_current_user),
    logger=Depends(get_request_logger_dep)
) -> ApiResponse:
    """Upload or resume a chunk for an existing upload session.

    Expects raw binary body. Optionally include Content-Range header:
        Content-Range: bytes {start}-{end}/{total}
    """
    logger.info(f"Receiving chunk for upload: {upload_id}")

    try:
        file_service = FileService(logger)

        # Read raw body
        chunk = await request.body()
        if not chunk:
            raise HTTPException(status_code=400, detail="Empty chunk body")

        # Get Content-Range header
        content_range = request.headers.get("content-range")

        session = await file_service.append_upload(
            upload_id, chunk, content_range, user_id=user.id
        )

        # Failed sessions are cleaned up immediately; completed sessions stay
        # available (2h TTL) until consumed by a conversion.
        if session.status == UploadStatusEnum.FAILED:
            background_tasks.add_task(file_service.remove_upload_session, upload_id)

        return ApiResponse.success(data={
            "upload_id": session.upload_id,
            "received_size": session.received_size,
            "total_size": session.total_size,
            "progress": session.progress,
            "status": session.status.value,
            "object_key": session.object_key if session.status == UploadStatusEnum.COMPLETED else None
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload chunk error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Upload chunk failed")


@router.get("/upload/{upload_id}", response_model=ApiResponse)
async def upload_status(
    upload_id: str,
    logger=Depends(get_request_logger_dep)
) -> ApiResponse:
    """Get the status of a resumable upload session."""
    logger.info(f"Checking upload status: {upload_id}")

    file_service = FileService(logger)
    session = await file_service.get_upload_status(upload_id)

    if not session:
        raise HTTPException(
            status_code=404,
            detail=f"Upload session not found: {upload_id}"
        )

    return ApiResponse.success(data={
        "upload_id": session.upload_id,
        "filename": session.filename,
        "received_size": session.received_size,
        "total_size": session.total_size,
        "progress": session.progress,
        "status": session.status.value,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
    })


# ------------------------------------------------------------------
# Async Task Endpoints (submit-and-poll pattern)
# ------------------------------------------------------------------


@router.post("/convert_async", status_code=202)
async def convert_async(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Document file to process"),
    enable_ocr: str = Form("false"),
    output_type: OutputType = OutputType.MARKDOWN,
    generate_picture_images: str = Form("false", description="Extract and embed images from PDF"),
    generate_table_images: str = Form("false", description="Generate table images alongside structure"),
    table_mode: Optional[str] = Form(None, pattern="^(fast|accurate)$", description="TableFormer mode: 'fast' or 'accurate'"),
    image_mode: Optional[ImageMode] = Form(None, description="Image reference mode: embedded, referenced, placeholder"),
    from_page: Optional[int] = Form(None, ge=1, description="Start page (1-based, inclusive)"),
    to_page: Optional[int] = Form(None, ge=1, description="End page (1-based, inclusive)"),
    callback_url: Optional[str] = Form(None, description="Webhook URL notified when the task reaches a terminal state"),
    timeout_seconds: Optional[int] = Form(None, ge=1, le=settings.TASK_PROCESSING_TIMEOUT_MAX, description="Max processing time override in seconds"),
    user: CurrentUserModel = Depends(get_current_user),
    logger=Depends(get_request_logger_dep),
):
    """Submit an async conversion task. Returns immediately with a task_id.

    Use from_page and to_page to convert only a specific page range (1-based, inclusive).
    """
    enable_ocr_bool = _parse_bool(enable_ocr)
    generate_images_bool = _parse_bool(generate_picture_images)
    generate_table_images_bool = _parse_bool(generate_table_images)

    logger.info(f"Submitting async conversion task: {file.filename}", extra={
        "enable_ocr": enable_ocr_bool,
        "output_type": output_type,
        "generate_picture_images": generate_images_bool,
        "generate_table_images": generate_table_images_bool,
        "table_mode": table_mode,
        "image_mode": image_mode,
        "from_page": from_page,
        "to_page": to_page,
        "client_ip": request.client.host if request.client else "unknown",
    })

    try:
        # Check if async task system is available
        task_service = request.app.state.task_service
        if task_service is None:
            raise HTTPException(
                status_code=503,
                detail="Async task system is not available (Redis not connected). "
                       "Use the synchronous /convert endpoint instead."
            )

        # Validate the callback URL and store the upload in object storage
        callback_url = _validate_callback_url(callback_url)
        file_service = FileService(logger)
        file_key, _ = await file_service.store_upload(file)

        # Submit task; drop the stored object again if the queue rejects it
        try:
            task = await task_service.submit_task(
                endpoint="convert",
                params={
                    "enable_ocr": enable_ocr_bool,
                    "output_type": output_type.value,
                    "generate_picture_images": generate_images_bool,
                    "generate_table_images": generate_table_images_bool,
                    "table_mode": table_mode,
                    "image_mode": image_mode.value if image_mode else None,
                    "from_page": from_page,
                    "to_page": to_page,
                },
                file_key=file_key,
                callback_url=callback_url,
                timeout_seconds=timeout_seconds,
            )
        except Exception:
            try:
                await get_storage_service().delete_object(file_key)
            except Exception as cleanup_exc:
                logger.warning(f"Orphan cleanup failed for {file_key}: {cleanup_exc}")
            raise

        return JSONResponse(
            status_code=202,
            content=ApiResponse.success(data=TaskSubmitResponse(
                task_id=task.task_id,
                status=task.status.value,
                message="Task submitted successfully. Poll the status URL or wait for the callback.",
                poll_url=f"/api/v1/tasks/{task.task_id}",
                result_url=f"/api/v1/tasks/{task.task_id}/result",
                callback_url=callback_url,
            ).model_dump()).model_dump(exclude_none=True, mode="json"),
        )

    except HTTPException:
        raise
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Error submitting async task: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to submit task")


@router.post("/convert_n_chunk_async", status_code=202)
async def convert_n_chunk_async(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Document file to process"),
    enable_ocr: str = Form("false"),
    ocr_langs: str = Form("id"),
    max_tokens: int = Form(512),
    output_type: OutputType = OutputType.MARKDOWN,
    chunk_type: ChunkType = ChunkType.HYBRID,
    generate_picture_images: str = Form("false", description="Extract and embed images from PDF"),
    generate_table_images: str = Form("false", description="Generate table images alongside structure"),
    table_mode: Optional[str] = Form(None, pattern="^(fast|accurate)$", description="TableFormer mode: 'fast' or 'accurate'"),
    image_mode: Optional[ImageMode] = Form(None, description="Image reference mode: embedded, referenced, placeholder"),
    from_page: Optional[int] = Form(None, ge=1, description="Start page (1-based, inclusive)"),
    to_page: Optional[int] = Form(None, ge=1, description="End page (1-based, inclusive)"),
    callback_url: Optional[str] = Form(None, description="Webhook URL notified when the task reaches a terminal state"),
    timeout_seconds: Optional[int] = Form(None, ge=1, le=settings.TASK_PROCESSING_TIMEOUT_MAX, description="Max processing time override in seconds"),
    user: CurrentUserModel = Depends(get_current_user),
    logger=Depends(get_request_logger_dep),
):
    """Submit an async convert-and-chunk task. Returns immediately with a task_id.

    Use from_page and to_page to convert only a specific page range (1-based, inclusive).
    """
    enable_ocr_bool = _parse_bool(enable_ocr)
    generate_images_bool = _parse_bool(generate_picture_images)
    generate_table_images_bool = _parse_bool(generate_table_images)

    logger.info(f"Submitting async convert+chunk task: {file.filename}", extra={
        "enable_ocr": enable_ocr_bool,
        "max_tokens": max_tokens,
        "chunk_type": chunk_type,
        "generate_picture_images": generate_images_bool,
        "generate_table_images": generate_table_images_bool,
        "table_mode": table_mode,
        "image_mode": image_mode,
        "from_page": from_page,
        "to_page": to_page,
        "client_ip": request.client.host if request.client else "unknown",
    })

    try:
        # Check if async task system is available
        task_service = request.app.state.task_service
        if task_service is None:
            raise HTTPException(
                status_code=503,
                detail="Async task system is not available (Redis not connected). "
                       "Use the synchronous /convert_n_chunk endpoint instead."
            )

        # Validate the callback URL and store the upload in object storage
        callback_url = _validate_callback_url(callback_url)
        file_service = FileService(logger)
        file_key, _ = await file_service.store_upload(file)

        # Submit task; drop the stored object again if the queue rejects it
        try:
            task = await task_service.submit_task(
                endpoint="convert_n_chunk",
                params={
                    "enable_ocr": enable_ocr_bool,
                    "ocr_langs": ocr_langs,
                    "max_tokens": max_tokens,
                    "output_type": output_type.value,
                    "chunk_type": chunk_type.value,
                    "generate_picture_images": generate_images_bool,
                    "generate_table_images": generate_table_images_bool,
                    "table_mode": table_mode,
                    "image_mode": image_mode.value if image_mode else None,
                    "from_page": from_page,
                    "to_page": to_page,
                },
                file_key=file_key,
                callback_url=callback_url,
                timeout_seconds=timeout_seconds,
            )
        except Exception:
            try:
                await get_storage_service().delete_object(file_key)
            except Exception as cleanup_exc:
                logger.warning(f"Orphan cleanup failed for {file_key}: {cleanup_exc}")
            raise

        return JSONResponse(
            status_code=202,
            content=ApiResponse.success(data=TaskSubmitResponse(
                task_id=task.task_id,
                status=task.status.value,
                message="Task submitted successfully. Poll the status URL or wait for the callback.",
                poll_url=f"/api/v1/tasks/{task.task_id}",
                result_url=f"/api/v1/tasks/{task.task_id}/result",
                callback_url=callback_url,
            ).model_dump()).model_dump(exclude_none=True, mode="json"),
        )

    except HTTPException:
        raise
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Error submitting async task: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to submit task")


@router.get("/tasks/{task_id}", response_model=ApiResponse)
async def get_task_status(
    task_id: str,
    request: Request,
    logger=Depends(get_request_logger_dep),
) -> ApiResponse:
    """Poll the status of an async conversion task.

    Returns the current status plus, for completed tasks, a presigned
    ``result_url`` and a small ``result_summary``. Fetch the full artifact
    via ``GET /api/v1/tasks/{task_id}/result``. Status and result expire
    7 days after completion.
    """
    logger.info(f"Polling task status: {task_id}")

    task_service = request.app.state.task_service
    if task_service is None:
        raise HTTPException(status_code=503, detail="Async task system is not available")

    task = await task_service.get_task(task_id)

    if task is None:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")

    response_data = {
        "task_id": task.task_id,
        "status": task.status.value,
        "endpoint": task.endpoint,
        "created_at": task.created_at,
        "started_at": task.started_at,
        "completed_at": task.completed_at,
        "processing_time": task.processing_time,
        "queue_expires_at": task.queue_expires_at,
        "processing_deadline": task.processing_deadline,
        "result_summary": task.result_summary,
        "callback_url": task.callback_url,
    }

    # Nudge pollers while the task is still in flight
    if task.status == TaskStatus.PENDING:
        response_data["poll_after"] = 10
    elif task.status == TaskStatus.PROCESSING:
        response_data["poll_after"] = 5

    if task.status == TaskStatus.COMPLETED:
        result_url = None
        if task.result_ref:
            try:
                result_url = await get_storage_service().presign_get_url(task.result_ref)
            except Exception as exc:
                logger.warning(f"Presign failed for task {task_id}: {exc}")
        response_data["result_url"] = result_url or f"/api/v1/tasks/{task_id}/result"
    elif task.error is not None:
        response_data["error"] = task.error

    return ApiResponse.success(data=response_data)


@router.get("/tasks/{task_id}/result")
async def get_task_result(
    task_id: str,
    request: Request,
    logger=Depends(get_request_logger_dep),
) -> Response:
    """Download the result artifact of a completed task.

    The artifact is served from object storage and expires 7 days after the
    task completes (along with its status entry).
    """
    logger.info(f"Fetching task result: {task_id}")

    task_service = request.app.state.task_service
    if task_service is None:
        raise HTTPException(status_code=503, detail="Async task system is not available")

    task = await task_service.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    if task.status != TaskStatus.COMPLETED:
        raise HTTPException(
            status_code=409,
            detail=f"Task is not completed yet (status={task.status.value})",
        )
    if not task.result_ref:
        raise HTTPException(status_code=404, detail="Result artifact not available")

    storage = get_storage_service()
    try:
        if not await storage.object_exists(task.result_ref):
            raise HTTPException(
                status_code=410,
                detail="Result artifact has expired (7-day retention)",
            )
        data = await storage.get_object_bytes(task.result_ref)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to fetch result artifact: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch result artifact")

    return Response(content=data, media_type="application/json")


@router.delete("/tasks/{task_id}", response_model=ApiResponse)
async def cancel_task(
    task_id: str,
    request: Request,
    logger=Depends(get_request_logger_dep),
) -> ApiResponse:
    """Cancel a pending task (only tasks still waiting in the queue)."""
    logger.info(f"Cancelling task: {task_id}")

    task_service = request.app.state.task_service
    if task_service is None:
        raise HTTPException(status_code=503, detail="Async task system is not available")

    task = await task_service.cancel_task(task_id)
    if task is None:
        raise HTTPException(
            status_code=404,
            detail=f"Task not found or not cancellable: {task_id}",
        )

    return ApiResponse.success(data={
        "task_id": task.task_id,
        "status": task.status.value,
    })


@router.get("/tasks", response_model=ApiResponse)
async def list_tasks(
    request: Request,
    limit: int = 20,
    offset: int = 0,
    logger=Depends(get_request_logger_dep),
) -> ApiResponse:
    """List recent async conversion tasks (newest first)."""
    logger.info(f"Listing tasks: limit={limit}, offset={offset}")

    task_service = request.app.state.task_service
    if task_service is None:
        raise HTTPException(status_code=503, detail="Async task system is not available")

    tasks = await task_service.list_tasks(limit=limit, offset=offset)

    task_list = [
        {
            "task_id": t.task_id,
            "status": t.status.value,
            "endpoint": t.endpoint,
            "created_at": t.created_at,
            "started_at": t.started_at,
            "completed_at": t.completed_at,
            "processing_time": t.processing_time,
        }
        for t in tasks
    ]

    return ApiResponse.success(data={"tasks": task_list, "count": len(task_list)})
