import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.endpoints.document import router as document_router
from app.middleware import CorrelationIdMiddleware, LoggerMiddleware
from app.models.api_response import ApiResponse
from app.services.callback_service import CallbackService
from app.services.conversion_service import (
    ConversionService,
    shutdown_shared_executor,
)
from app.services.storage_service import (
    get_storage_service,
    init_storage_service,
    set_storage_service,
)
from app.services.task_service import TaskService
from app.utils.error import ErrorResponse
from app.utils.redis_client import init_redis, close_redis, check_redis_health
from app.workers.task_worker import TaskWorker
from config import (
    get_request_logger_dep,
    get_service_logger,
    root_logger,
    settings,
)


def ensure_temp_directory() -> str:
    """Create the local scratch directory if it doesn't exist."""
    temp_dir = Path(settings.TEMP_DIR)

    try:
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_dir.chmod(0o755)

        root_logger.info(f"Temp directory ensured at: {temp_dir.absolute()}")

        if settings.DEBUG:
            root_logger.debug(f"Temp directory contents: {list(temp_dir.glob('*'))}")

        return str(temp_dir.absolute())

    except Exception as e:
        root_logger.error(f"Failed to create temp directory: {str(e)}")
        fallback_dir = Path("/tmp/docling-temp")
        fallback_dir.mkdir(parents=True, exist_ok=True)
        fallback_dir.chmod(0o777)
        settings.TEMP_DIR = str(fallback_dir)
        root_logger.warning(f"Using fallback temp directory: {fallback_dir}")
        return str(fallback_dir)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: initialize shared services on startup, clean up on shutdown."""
    # Startup
    root_logger.info(f"Starting {settings.APP_NAME} in {settings.APP_ENV} mode")
    root_logger.info(f"Debug mode: {'ENABLED' if settings.DEBUG else 'DISABLED'}")

    ensure_temp_directory()

    # Initialize singleton ConversionService (shared executor + pre-warmed converter)
    service_logger = get_service_logger("conversion")
    cs = ConversionService(service_logger)
    init_converter = await cs.initialize_converter()
    if init_converter is None:
        root_logger.warning("Converter initialization at startup failed, will init on demand")
    app.state.conversion_service = cs

    # Initialize object storage (MinIO, or local-disk fallback for dev)
    try:
        storage = init_storage_service(get_service_logger("storage"))
        await storage.ensure_bucket()
        await storage.ensure_result_lifecycle()
        app.state.storage_service = storage
        mode = "MinIO" if storage.enabled else "local-disk fallback"
        root_logger.info(f"Object storage initialized ({mode})")
    except Exception as exc:
        root_logger.error(f"Object storage initialization failed: {exc}")
        raise  # Fail fast: uploading and results both depend on storage

    # Initialize Redis and async task system
    try:
        redis_client = await init_redis(settings.REDIS_URL)
        task_service = TaskService(redis_client, get_service_logger("task_service"))
        app.state.task_service = task_service

        # Start background task worker (consumer + janitor + webhook callbacks)
        callback_service = CallbackService(get_service_logger("callback"))
        worker = TaskWorker(task_service, cs, storage, callback_service)
        app.state.task_worker = worker
        await worker.start()
        root_logger.info("Async task system initialized (Redis + worker + janitor)")
    except Exception as exc:
        root_logger.warning(
            f"Redis/worker initialization failed: {exc}. "
            "Async task endpoints will not be available."
        )
        app.state.task_service = None
        app.state.task_worker = None

    yield

    # Shutdown
    # Stop the worker first
    worker = getattr(app.state, "task_worker", None)
    if worker:
        await worker.stop()

    # Close Redis connection
    await close_redis()

    set_storage_service(None)
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

# CORS middleware. A wildcard origin cannot be combined with credentials;
# production deployments should set CORS_ORIGINS to explicit origins.
cors_origins = [origin.strip() for origin in settings.CORS_ORIGINS.split(",")]
allow_credentials = True
if "*" in cors_origins:
    allow_credentials = False
    if settings.APP_ENV == "prod":
        root_logger.warning(
            "CORS_ORIGINS is '*' in production - restrict it to real origins"
        )
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=allow_credentials,
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
async def health_check(request: Request, logger=Depends(get_request_logger_dep)):
    """Health check endpoint with aggregate component status.

    Returns 200 only when every component (converter, Redis, object storage,
    worker) is healthy; returns 503 otherwise.
    """
    logger.info("Health check called")

    cs = getattr(app.state, "conversion_service", None)
    converter_ok = bool(cs and cs.converter)

    redis_ok = await check_redis_health()

    try:
        storage_ok = await get_storage_service().health()
    except Exception:
        storage_ok = False

    worker = getattr(app.state, "task_worker", None)
    worker_ok = worker.is_running if worker else False

    healthy = converter_ok and redis_ok and storage_ok and worker_ok

    payload = {
        "status": "healthy" if healthy else "unhealthy",
        "timestamp": time.time(),
        "converter_status": "healthy" if converter_ok else "unhealthy",
        "redis_status": "healthy" if redis_ok else "unavailable",
        "storage_status": "healthy" if storage_ok else "unavailable",
        "task_worker_status": "running" if worker_ok else "stopped",
        "environment": settings.APP_ENV,
        "request_id": request.headers.get("X-Request-ID"),
    }

    if healthy:
        return ApiResponse.success(data=payload)

    return JSONResponse(
        status_code=503,
        content=ApiResponse.error(
            error_message="Service is not fully healthy",
            error_type="UNHEALTHY",
            data=payload,
        ).model_dump(exclude_none=True, mode="json"),
    )


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


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Wrap HTTPException responses in the standard ApiResponse envelope."""
    logger = get_request_logger_dep(request)
    if exc.status_code >= 500:
        logger.error(f"HTTP error {exc.status_code}: {exc.detail}")
    else:
        logger.warning(f"HTTP error {exc.status_code}: {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content=ApiResponse.error(
            error_message=str(exc.detail),
            error_type=f"HTTP_{exc.status_code}",
        ).model_dump(exclude_none=True, mode="json"),
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Wrap validation errors (422) in the standard ApiResponse envelope."""
    logger = get_request_logger_dep(request)
    logger.warning(f"Request validation failed: {exc.errors()}")
    return JSONResponse(
        status_code=422,
        content=ApiResponse.error(
            error_message="Request validation failed",
            error_type="VALIDATION_ERROR",
            data={"errors": jsonable_encoder(exc.errors())},
        ).model_dump(exclude_none=True, mode="json"),
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
