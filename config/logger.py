import logging
import json
import sys
from typing import Dict, Any, Optional
from .loader import settings
from .context import context

class ContextFilter(logging.Filter):
    """Adds request context to log records"""
    
    def filter(self, record: logging.LogRecord) -> bool:
        # Add request ID to all logs
        record.request_id = context.get_request_id()
        
        # Add user context if available
        user = context.get_current_user()
        if user:
            record.user_id = user.get("id", "unknown")
            record.username = user.get("username", "unknown")
        
        return True

class JSONFormatter(logging.Formatter):
    """Formats logs as JSON for production"""
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "request_id": getattr(record, "request_id", "no-request-id"),
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }
        
        # Add user context
        if hasattr(record, "user_id"):
            log_data["user_id"] = record.user_id
        if hasattr(record, "username"):
            log_data["username"] = record.username
        
        # Add exception info
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_data)

def setup_root_logger():
    """Configure root logger based on environment"""
    root_logger = logging.getLogger()
    root_logger.setLevel(settings.LOG_LEVEL)
    
    # Clear existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Create handler
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(ContextFilter())
    
    # Environment-specific formatting
    if settings.APP_ENV == "prod":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)-8s] [%(request_id)s] "
            "%(name)s:%(lineno)d - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))
    
    root_logger.addHandler(handler)
    
    # Suppress noisy libraries
    if settings.APP_ENV == "prod":
        logging.getLogger("uvicorn").setLevel("WARNING")
        logging.getLogger("asyncio").setLevel("WARNING")
    
    return root_logger

# Initialize root logger
root_logger = setup_root_logger()

def get_request_logger(name: str, extra: Optional[Dict[str, Any]] = None):
    """
    Get a logger that automatically includes request context
    """
    logger = logging.getLogger(f"app.{name}")
    return logging.LoggerAdapter(logger, extra or {})

def get_service_logger(service_name: str) -> logging.LoggerAdapter:
    """
    Get a service logger with context for non-request operations
    
    Args:
        service_name: Name of the service
        
    Returns:
        LoggerAdapter with appropriate context
    """
    logger = logging.getLogger(f"app.services.{service_name}")
    return logging.LoggerAdapter(
        logger,
        {
            "service": service_name,
            "request_id": "system",
            "client_ip": "system"
        }
    )