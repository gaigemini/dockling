import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from config.context import context
from config import get_request_logger

class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Generates and propagates request correlation IDs"""
    
    async def dispatch(self, request: Request, call_next):
        # 1. Get or generate correlation ID
        request_id = request.headers.get("X-Request-ID") or request.headers.get("X-Correlation-ID")
        if not request_id:
            request_id = str(uuid.uuid4())
        
        # 2. Set context for this request
        token = context.set_request_id(request_id)
        
        try:
            # 3. Process request
            response: Response = await call_next(request)
            
            # 4. Add correlation ID to response headers
            response.headers["X-Request-ID"] = request_id
            
            return response
            
        finally:
            # 5. Clean up context
            context.request_id.reset(token)

class LoggerMiddleware(BaseHTTPMiddleware):
    """Attaches request-scoped logger to request.state"""
    
    async def dispatch(self, request: Request, call_next):
        # Create request-scoped logger
        logger = get_request_logger(
            name=f"route:{request.url.path}",
            extra={
                "method": request.method,
                "path": request.url.path,
                "client_ip": request.client.host if request.client else "unknown"
            }
        )
        
        # Add logger to request state
        request.state.logger = logger
        
        # Log request start
        logger.info(
            f"Incoming request: {request.method} {request.url.path} "
            f"from {request.client.host if request.client else 'unknown'}"
        )
        
        try:
            response = await call_next(request)
            logger.info(
                f"Request completed: {request.method} {request.url.path} "
                f"Status: {response.status_code}"
            )
            return response
        except Exception as e:
            logger.error(f"Request failed: {str(e)}", exc_info=True)
            raise