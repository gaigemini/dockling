import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.endpoints.document import router as document_router
from app.middleware import CorrelationIdMiddleware, LoggerMiddleware
from app.models.api_response import ApiResponse
from app.services.conversion_service import (
    ConversionService,
    shutdown_shared_executor,
)
from app.utils.error import ErrorResponse
from config import (
    get_request_logger_dep,
    get_service_logger,
    root_logger,
    settings,
)


def ensure_upload_directory() -> str:
    """Create upload directory if it doesn't exist and set proper permissions."""
    upload_dir = Path(settings.UPLOAD_DIR)

    try:
        upload_dir.mkdir(parents=True, exist_ok=True)
        upload_dir.chmod(0o755)

        root_logger.info(f"Upload directory ensured at: {upload_dir.absolute()}")

        if settings.DEBUG:
            root_logger.debug(f"Upload directory contents: {list(upload_dir.glob('*'))}")

        return str(upload_dir.absolute())

    except Exception as e:
        root_logger.error(f"Failed to create upload directory: {str(e)}")
        fallback_dir = Path("/tmp/uploads")
        fallback_dir.mkdir(parents=True, exist_ok=True)
        fallback_dir.chmod(0o777)
        root_logger.warning(f"Using fallback directory: {fallback_dir}")
        return str(fallback_dir)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: initialize shared services on startup, clean up on shutdown."""
    # Startup
    root_logger.info(f"Starting {settings.APP_NAME} in {settings.APP_ENV} mode")
    root_logger.info(f"Debug mode: {'ENABLED' if settings.DEBUG else 'DISABLED'}")

    ensure_upload_directory()

    # Initialize singleton ConversionService (shared executor + pre-warmed converter)
    service_logger = get_service_logger("conversion")
    cs = ConversionService(service_logger)
    init_result = await cs.initialize_converter()
    if not init_result:
        root_logger.warning("Converter initialization at startup failed, will init on demand")
    app.state.conversion_service = cs

    yield

    # Shutdown
    shutdown_shared_executor()
    root_logger.info("Docling API shutdown completed")


app = FastAPI(
    title=settings.APP_NAME,
    description="Production-ready API for document processing using Docling - Text and Table Extraction",
    version="2.0.0",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
    lifespan=lifespan
)

# Register middleware (order matters: CorrelationId first, then Logger)
app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(LoggerMiddleware)

# CORS middleware
cors_origins = [origin.strip() for origin in settings.CORS_ORIGINS.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(document_router)


@app.get("/")
async def root(request: Request, logger=Depends(get_request_logger_dep)) -> ApiResponse:
    """Root endpoint with logging."""
    logger.info("Root endpoint accessed")
    return ApiResponse.success(data={
        "app": settings.APP_NAME,
        "environment": settings.APP_ENV,
        "debug": settings.DEBUG,
        "version": "2.0.0",
        "status": "running",
        "focus": "text_and_tables",
        "request_id": request.headers.get("X-Request-ID")
    })


@app.get("/health")
async def health_check(request: Request, logger=Depends(get_request_logger_dep)) -> ApiResponse:
    """Health check endpoint."""
    logger.info("Health check called")

    cs = getattr(app.state, "conversion_service", None)
    converter_status = "healthy" if cs and cs.converter else "unhealthy"

    return ApiResponse.success(data={
        "status": "healthy",
        "timestamp": time.time(),
        "converter_status": converter_status,
        "environment": settings.APP_ENV,
        "request_id": request.headers.get("X-Request-ID")
    })


# Error handlers

@app.exception_handler(ErrorResponse)
async def custom_error_handler(request: Request, exc: ErrorResponse):
    logger = get_request_logger_dep(request)
    logger.error(f"Application error: {exc.error_message}")
    return JSONResponse(
        status_code=400,
        content=ApiResponse.error(
            error_message=exc.error_message,
            error_type=exc.error_code,
            data=exc.data
        ).model_dump(exclude_none=True)
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger = get_request_logger_dep(request)
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content=ApiResponse.error(
            error_message="Internal server error",
            error_type="INTERNAL_ERROR"
        ).model_dump(exclude_none=True)
    )
