import uuid
from starlette.requests import Request
from config.context import context
from config import get_request_logger


class CorrelationIdMiddleware:
    """Pure ASGI middleware - faster than BaseHTTPMiddleware.
    Generates and propagates request correlation IDs.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # 1. Get or generate correlation ID from headers
        headers = dict(scope.get("headers", []))
        request_id = (
            headers.get(b"x-request-id")
            or headers.get(b"x-correlation-id")
            or str(uuid.uuid4()).encode()
        )

        # 2. Set context for this request
        token = context.set_request_id(request_id.decode("utf-8"))
        scope["request_id"] = request_id

        # 3. Wrap send to inject correlation ID into response headers
        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.append((b"X-Request-ID", request_id))
                message["headers"] = response_headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            # 4. Clean up context
            context.request_id.reset(token)


class LoggerMiddleware:
    """Pure ASGI middleware - faster than BaseHTTPMiddleware.
    Attaches request-scoped logger and logs requests.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Reconstruct Request from scope for URL and client info
        request = Request(scope=scope)

        # Create request-scoped logger
        logger = get_request_logger(
            name=f"route:{request.url.path}",
            extra={
                "method": request.method,
                "path": request.url.path,
                "client_ip": request.client.host if request.client else "unknown"
            }
        )

        # Store logger in scope so downstream can access via request.state
        scope["logger"] = logger
        scope["state"] = {"logger": logger}

        # Log request start
        logger.info(
            f"Incoming request: {request.method} {request.url.path} "
            f"from {request.client.host if request.client else 'unknown'}"
        )

        status_code = 200

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 200)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
            logger.info(
                f"Request completed: {request.method} {request.url.path} "
                f"Status: {status_code}"
            )
        except Exception as e:
            logger.error(f"Request failed: {str(e)}", exc_info=True)
            raise