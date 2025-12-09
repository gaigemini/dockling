from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from contextlib import asynccontextmanager
import time

from config import settings, root_logger, get_request_logger_dep
from app.middleware import CorrelationIdMiddleware, LoggerMiddleware
from app.routers.document import router as document_router
from app.services.conversion_service import ConversionService

# Global service instance
conversion_service = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup code
    root_logger.info(f"🚀 Starting {settings.APP_NAME} in {settings.APP_ENV} mode")
    root_logger.info(f"Debug mode: {'ENABLED' if settings.DEBUG else 'DISABLED'}")
    
    global conversion_service
    
    try:
        # Initialize conversion service
        conversion_service = ConversionService(root_logger)
        init_result = await conversion_service.initialize_converter()
        if not init_result:
            root_logger.error("Failed to initialize converter on startup")
        else:
            root_logger.info("Document converter initialized successfully")
    except Exception as e:
        root_logger.error(f"Startup initialization failed: {str(e)}")
    
    yield  # App runs here
    
    # Shutdown code
    root_logger.info("Document Processing API shutdown completed")

app = FastAPI(
    title=settings.APP_NAME,
    description="Production-ready API for document processing using Docling - Text and Table Extraction",
    version="2.0.0",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
    lifespan=lifespan
)

# Register middleware (order matters!)
app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(LoggerMiddleware)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(document_router)

@app.get("/")
async def root(request: Request, logger = Depends(get_request_logger_dep)):
    """Root endpoint with logging"""
    logger.info("Root endpoint accessed")
    return {
        "app": settings.APP_NAME,
        "environment": settings.APP_ENV,
        "debug": settings.DEBUG,
        "version": "2.0.0",
        "status": "running",
        "focus": "text_and_tables",
        "request_id": request.headers.get("X-Request-ID")
    }

@app.get("/health")
async def health_check(request: Request, logger = Depends(get_request_logger_dep)):
    """Health check endpoint"""
    logger.info("Health check called")
    
    converter_status = "healthy" if conversion_service and conversion_service.converter else "unhealthy"
    
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "converter_status": converter_status,
        "environment": settings.APP_ENV,
        "request_id": request.headers.get("X-Request-ID")
    }

# Error handlers
@app.exception_handler(500)
async def internal_server_error_handler(request: Request, exc: Exception):
    logger = get_request_logger_dep(request)
    logger.error(f"Internal server error: {exc}", exc_info=True)
    return Response(
        content=ErrorResponse(
            error="Internal server error",
            details=str(exc.detail) if hasattr(exc, 'detail') else str(exc)
        ).json(),
        status_code=500,
        media_type="application/json"
    )

@app.exception_handler(400)
async def bad_request_handler(request: Request, exc: Exception):
    logger = get_request_logger_dep(request)
    logger.warning(f"Bad request: {exc}")
    return Response(
        content=ErrorResponse(
            error="Bad request",
            details=str(exc.detail) if hasattr(exc, 'detail') else str(exc)
        ).json(),
        status_code=400,
        media_type="application/json"
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=settings.DEBUG)