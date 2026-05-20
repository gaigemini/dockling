"""Backward-compatible re-exports from app/dependencies."""

from app.dependencies.logger import get_request_logger_dep

__all__ = [
    "get_request_logger_dep",
]