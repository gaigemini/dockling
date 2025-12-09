from fastapi import APIRouter, Form, UploadFile, File, HTTPException, BackgroundTasks, Depends, Request
import time

from config.dependencies import get_current_user, get_request_logger_dep
from app.services.file_service import FileService
from app.services.conversion_service import ConversionService
from ..models import ApiResponse, ErrorResponse, OutputType, ChunkType

router = APIRouter(
    prefix="/api/v1",
    tags=["documents"],
    dependencies=[Depends(get_current_user)]  # Auth protection
)

@router.post("/convert", response_model=ApiResponse)
async def convert(
    background_tasks: BackgroundTasks,
    request: Request,
    file: UploadFile = File(..., description="Document file to process"),
    enable_ocr: str = Form("false"),
    output_type: OutputType = OutputType.MARKDOWN,
    logger = Depends(get_request_logger_dep)
):
    """Process uploaded document dengan Docling - Focus on Text and Tables"""
    start_time = time.time()

    # Convert enable_ocr string to boolean
    enable_ocr_bool = enable_ocr.lower() in ["true", "1", "yes", "on", "y"]

    logger.info(
        f"Processing document: {file.filename}", extra={
            "enable_ocr": enable_ocr_bool,
            "output_type": output_type,
            "client_ip": request.client.host if request.client else "unknown"
        }
    )

    try:
        # Initialize services with request-scoped logger
        file_service = FileService(logger)
        conversion_service = ConversionService(logger)

        # Validate file
        if not file.filename:
            raise HTTPException(status_code=400, detail="No file provided")

        # Save uploaded file
        file_path = await file_service.save_upload_file(file)

        # Schedule cleanup
        background_tasks.add_task(file_service.cleanup_file, file_path)

        # Initialize converter dengan user settings
        success = await conversion_service.initialize_converter(enable_ocr_bool)
        if not success:
            logger.warning("Using fallback converter configuration")

        # Process document
        result = await conversion_service.convert(file_path, output_type)

        if result.status == 0:
            result.data["processing_time"] = time.time() - start_time

        logger.info("Document processing completed", extra={
            "success": result.status == 0,
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
    file: UploadFile = File(..., description="Document file to process"),
    enable_ocr: str = Form("false"),
    ocr_langs: str = Form("id"),
    max_tokens: int = Form(512),
    output_type: OutputType = OutputType.MARKDOWN,
    chunk_type: ChunkType = ChunkType.HYBRID,
    logger = Depends(get_request_logger_dep)
):
    """Chunking document"""
    start_time = time.time()

    # Convert enable_ocr string to boolean
    enable_ocr_bool = enable_ocr.lower() in ["true", "1", "yes", "on", "y"]

    # Process OCR languages
    ocr_langs_list = [lang.strip() for lang in ocr_langs.split(",")]

    logger.info(
        f"Processing document with chunking: {file.filename}", extra={
            "enable_ocr": enable_ocr_bool,
            "max_tokens": max_tokens,
            "chunk_type": chunk_type,
            "client_ip": request.client.host if request.client else "unknown"
        }
    )

    try:
        # Initialize services with request-scoped logger
        file_service = FileService(logger)
        conversion_service = ConversionService(logger)

        # Validate file
        if not file.filename:
            raise HTTPException(status_code=400, detail="No file provided")

        # Save uploaded file
        file_path = await file_service.save_upload_file(file)

        # Schedule cleanup
        background_tasks.add_task(file_service.cleanup_file, file_path)

        # Initialize converter dengan user settings
        success = await conversion_service.initialize_converter(enable_ocr_bool, ocr_langs_list)
        if not success:
            logger.warning("Using fallback converter configuration")

        # Process document dengan chunking
        result = await conversion_service.convert_and_chunk(
            file_path, 
            max_tokens, 
            output_type, 
            chunk_type
        )

        if result.status == 0:
            result.data["processing_time"] = time.time() - start_time

        logger.info("Document conversion and chunking completed", extra={
            "success": result.status == 0,
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