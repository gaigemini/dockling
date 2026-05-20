"""Logger dependency for FastAPI endpoints."""

from fastapi import Request

from config.logger import get_request_logger


def get_request_logger_dep(request: Request):
    """Dependency to get request-scoped logger."""
    if not hasattr(request.state, "logger"):
        request.state.logger = get_request_logger(
            name=f"route:{request.url.path}",
            extra={
                "method": request.method,
                "path": request.url.path,
                "client_ip": request.client.host if request.client else "unknown"
            }
        )
    return request.state.logger
