"""Document processing endpoints with streaming and resumable upload support."""

import time
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile

from app.dependencies.auth import get_current_user
from app.dependencies.logger import get_request_logger_dep
from app.models.api_response import ApiResponse
from app.models.document_model import ChunkType, OutputType, UploadSessionModel, UploadStatusEnum
from app.services.file_service import FileService
from config import settings

router = APIRouter(
    prefix="/api/v1",
    tags=["documents"],
    dependencies=[Depends(get_current_user)]
)


def _parse_bool(value: str) -> bool:
    """Parse string to boolean."""
    return value.lower() in ["true", "1", "yes", "on", "y"]


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


async def _prepare_file(
    file: UploadFile,
    upload_id: Optional[str],
    background_tasks: BackgroundTasks,
    logger
) -> tuple:
    """Prepare file for conversion: stream BytesIO or saved file path.

    Returns (buffer_or_path, filename, is_streaming)
    - If streaming: (BytesIO, filename, True)
    - If file-based: (file_path, filename, False)
    """
    file_service = FileService(logger)

    # If upload_id is provided, use previously uploaded file
    if upload_id:
        file_path = file_service.get_upload_file_path(upload_id)
        if not file_path:
            raise HTTPException(
                status_code=404,
                detail=f"Upload session not found or not completed: {upload_id}"
            )
        # Get session for filename
        session = file_service.get_upload_status(upload_id)
        filename = session.filename if session else "unknown"
        logger.info(f"Using pre-uploaded file for conversion: {upload_id}", extra={
            "filename": filename,
            "file_path": file_path
        })
        # Schedule cleanup of the upload session
        background_tasks.add_task(file_service.remove_upload_session, upload_id)
        return file_path, filename, False

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
        # Save to disk first (for large files)
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
    logger=Depends(get_request_logger_dep)
) -> ApiResponse:
    """Process uploaded document with Docling - supports streaming and resumable upload."""
    start_time = time.time()
    enable_ocr_bool = _parse_bool(enable_ocr)

    logger.info(f"Processing document: {file.filename if file else upload_id}", extra={
        "enable_ocr": enable_ocr_bool,
        "output_type": output_type,
        "use_stream": use_stream,
        "upload_id": upload_id,
        "client_ip": request.client.host if request.client else "unknown"
    })

    try:
        # Prepare file source (stream or file path)
        source, filename, is_streaming = await _prepare_file(
            file, upload_id, background_tasks, logger
        )

        # Get singleton conversion service from app state
        cs = request.app.state.conversion_service

        # Initialize converter with user settings
        await cs.initialize_converter(enable_ocr_bool, logger=logger)

        # Process document
        if is_streaming:
            result = await cs.convert_stream(source, filename, output_type, logger=logger)
        else:
            result = await cs.convert(source, output_type, logger=logger)

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
        raise HTTPException(
            status_code=500, detail=f"Internal server error: {str(e)}")


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
    logger=Depends(get_request_logger_dep)
) -> ApiResponse:
    """Convert and chunk document - supports streaming and resumable upload."""
    start_time = time.time()
    enable_ocr_bool = _parse_bool(enable_ocr)
    ocr_langs_list = [lang.strip() for lang in ocr_langs.split(",")]

    logger.info(f"Processing document with chunking: {file.filename if file else upload_id}", extra={
        "enable_ocr": enable_ocr_bool,
        "max_tokens": max_tokens,
        "chunk_type": chunk_type,
        "use_stream": use_stream,
        "upload_id": upload_id,
        "client_ip": request.client.host if request.client else "unknown"
    })

    try:
        # Prepare file source (stream or file path)
        source, filename, is_streaming = await _prepare_file(
            file, upload_id, background_tasks, logger
        )

        # Get singleton conversion service from app state
        cs = request.app.state.conversion_service

        # Initialize converter with user settings
        await cs.initialize_converter(enable_ocr_bool, ocr_langs_list, logger=logger)

        # Process document with chunking
        if is_streaming:
            result = await cs.convert_and_chunk_stream(
                source, filename, max_tokens, output_type, chunk_type, logger=logger
            )
        else:
            result = await cs.convert_and_chunk(
                source, max_tokens, output_type, chunk_type, logger=logger
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
        raise HTTPException(
            status_code=500, detail=f"Internal server error: {str(e)}")


# ------------------------------------------------------------------
# Resumable Upload Endpoints
# ------------------------------------------------------------------


@router.post("/upload/init", response_model=ApiResponse)
async def upload_init(
    request: Request,
    filename: str = Form(..., description="Original file name"),
    total_size: int = Form(..., ge=1, description="Total file size in bytes"),
    mime_type: Optional[str] = Form(None, description="MIME type of the file"),
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
        session = file_service.init_upload(filename, total_size, mime_type)

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
        raise HTTPException(status_code=500, detail=f"Upload initiation failed: {str(e)}")


@router.put("/upload/{upload_id}", response_model=ApiResponse)
async def upload_chunk(
    upload_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
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

        session = await file_service.append_upload(upload_id, chunk, content_range)

        # Schedule cleanup for expired/failed sessions
        if session.status in (UploadStatusEnum.COMPLETED, UploadStatusEnum.FAILED):
            background_tasks.add_task(file_service.remove_upload_session, upload_id)

        return ApiResponse.success(data={
            "upload_id": session.upload_id,
            "received_size": session.received_size,
            "total_size": session.total_size,
            "progress": session.progress,
            "status": session.status.value,
            "file_path": session.file_path if session.status == UploadStatusEnum.COMPLETED else None
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload chunk error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Upload chunk failed: {str(e)}")


@router.get("/upload/{upload_id}", response_model=ApiResponse)
async def upload_status(
    upload_id: str,
    logger=Depends(get_request_logger_dep)
) -> ApiResponse:
    """Get the status of a resumable upload session."""
    logger.info(f"Checking upload status: {upload_id}")

    file_service = FileService(logger)
    session = file_service.get_upload_status(upload_id)

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
