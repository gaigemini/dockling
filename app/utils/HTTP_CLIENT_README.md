# CorrelatedHttpClient

A generic HTTPX wrapper that automatically injects correlation IDs into all outgoing HTTP requests, enabling distributed tracing across microservices.

## Overview

The `CorrelatedHttpClient` wraps HTTPX's `AsyncClient` to automatically include the current request's correlation ID (`X-Request-ID` header) in all outgoing HTTP requests. This ensures end-to-end request tracing across service boundaries.

## Features

- ✅ Automatic correlation ID injection from request context
- ✅ Supports all HTTP methods (GET, POST, PUT, PATCH, DELETE, etc.)
- ✅ Preserves and merges with existing headers
- ✅ Configurable timeout, SSL verification, and base URL
- ✅ Context manager support for resource management
- ✅ Fully tested and production-ready

## Installation

No additional dependencies required - uses existing `httpx` package already in `requirements.txt`.

## Quick Start

### Basic Usage

```python
from app.utils.http_client import CorrelatedHttpClient

# Create client
client = CorrelatedHttpClient(base_url="https://api.example.com")

# Make requests - correlation ID is automatically injected
response = await client.get("/users/123")
response = await client.post("/users", json={"name": "John"})
```

### In a FastAPI Endpoint

```python
from fastapi import APIRouter, Depends
from app.utils.http_client import CorrelatedHttpClient
from config import get_request_logger_dep

router = APIRouter()

@router.get("/external-data")
async def get_external_data(logger=Depends(get_request_logger_dep)):
    # The incoming request's correlation ID will be automatically
    # injected into this outgoing request
    client = CorrelatedHttpClient(base_url="https://api.example.com")
    response = await client.get("/data")
    return response.json()
```

## API Reference

### CorrelatedHttpClient

#### Constructor

```python
CorrelatedHttpClient(
    base_url: Optional[str] = None,
    timeout: Optional[httpx.Timeout] = None,
    verify_ssl: bool = True,
    **kwargs
)
```

**Parameters:**
- `base_url`: Base URL for all requests (e.g., `"https://api.example.com"`)
- `timeout`: HTTPX timeout configuration (default: 10 seconds)
- `verify_ssl`: Whether to verify SSL certificates (default: `True`)
- `**kwargs`: Additional arguments passed to `httpx.AsyncClient`

#### HTTP Methods

All HTTP methods support the same parameters as HTTPX, with automatic correlation ID injection:

##### GET
```python
async def get(
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: Optional[httpx.Timeout] = None,
    **kwargs
) -> httpx.Response
```

##### POST
```python
async def post(
    url: str,
    *,
    data: Optional[Union[Dict[str, Any], str]] = None,
    json: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: Optional[httpx.Timeout] = None,
    **kwargs
) -> httpx.Response
```

##### PUT
```python
async def put(
    url: str,
    *,
    data: Optional[Union[Dict[str, Any], str]] = None,
    json: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: Optional[httpx.Timeout] = None,
    **kwargs
) -> httpx.Response
```

##### PATCH
```python
async def patch(
    url: str,
    *,
    data: Optional[Union[Dict[str, Any], str]] = None,
    json: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: Optional[httpx.Timeout] = None,
    **kwargs
) -> httpx.Response
```

##### DELETE
```python
async def delete(
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: Optional[httpx.Timeout] = None,
    **kwargs
) -> httpx.Response
```

##### Generic Request
```python
async def request(
    method: str,
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    timeout: Optional[httpx.Timeout] = None,
    **kwargs
) -> httpx.Response
```

### Context Manager

```python
from app.utils.http_client import get_correlated_client

async with get_correlated_client(base_url="https://api.example.com") as client:
    response = await client.get("/health")
```

## Examples

### 1. Basic GET Request
```python
client = CorrelatedHttpClient(base_url="https://api.example.com")
response = await client.get("/users/123")
data = response.json()
```

### 2. POST with JSON Payload
```python
client = CorrelatedHttpClient(base_url="https://api.example.com")
response = await client.post(
    "/users",
    json={"name": "John Doe", "email": "john@example.com"}
)
```

### 3. Custom Headers (Preserved and Merged)
```python
client = CorrelatedHttpClient(base_url="https://api.example.com")
response = await client.get(
    "/protected-resource",
    headers={
        "Authorization": "Bearer my-token",
        "Accept": "application/json"
    }
)
# Result: Headers include Authorization, Accept, AND X-Request-ID
```

### 4. Custom Timeout
```python
import httpx

custom_timeout = httpx.Timeout(30.0, connect=10.0)
client = CorrelatedHttpClient(
    base_url="https://api.example.com",
    timeout=custom_timeout
)
response = await client.get("/slow-endpoint")
```

### 5. Disable SSL Verification (Dev/Test Only)
```python
client = CorrelatedHttpClient(
    base_url="https://localhost:8080",
    verify_ssl=False
)
response = await client.get("/health")
```

### 6. Query Parameters
```python
client = CorrelatedHttpClient(base_url="https://api.example.com")
response = await client.get(
    "/search",
    params={"q": "search term", "page": 1, "limit": 10}
)
```

### 7. Form Data POST
```python
client = CorrelatedHttpClient(base_url="https://api.example.com")
response = await client.post(
    "/submit-form",
    data={"field1": "value1", "field2": "value2"}
)
```

### 8. Multiple Requests (Same Correlation ID)
```python
client = CorrelatedHttpClient(base_url="https://api.example.com")

# All requests will have the same correlation ID
users = await client.get("/users")
posts = await client.get("/posts")
comments = await client.get("/comments")
```

## How It Works

1. **Context Retrieval**: When making a request, the client retrieves the current correlation ID from `config.context.get_request_id()`
2. **Header Injection**: The correlation ID is added to the request headers as `X-Request-ID`
3. **Header Merging**: If custom headers are provided, they are preserved and merged with the correlation ID
4. **Request Execution**: The request is executed with the augmented headers

### Correlation ID Flow

```
Incoming Request (X-Request-ID: abc-123)
    ↓
CorrelationIdMiddleware extracts ID and stores in context
    ↓
Your endpoint code executes
    ↓
CorrelatedHttpClient retrieves ID from context
    ↓
Outgoing Request includes X-Request-ID: abc-123
    ↓
External service receives request with correlation ID
```

## Migration from Manual Header Injection

### Before (Manual)
```python
import httpx
from config.context import context

async def old_way():
    headers = {"Authorization": "Bearer token"}
    req_id = context.get_request_id()
    if req_id and req_id != "no-request-id":
        headers["X-Request-ID"] = req_id
    
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
```

### After (Automatic)
```python
from app.utils.http_client import CorrelatedHttpClient

async def new_way():
    client = CorrelatedHttpClient()
    response = await client.get(url, headers={"Authorization": "Bearer token"})
    # X-Request-ID is automatically injected!
```

## Testing

The client includes comprehensive unit tests in `tests/unit/test_http_client.py`:

```bash
# Run tests
python -m pytest tests/unit/test_http_client.py -v

# Run with coverage
python -m pytest tests/unit/test_http_client.py --cov=app.utils.http_client
```

## Best Practices

1. **Always use CorrelatedHttpClient** for service-to-service communication
2. **Set base_url** when making multiple requests to the same service
3. **Use context manager** (`get_correlated_client`) for better resource management
4. **Configure appropriate timeouts** for your use case
5. **Never disable SSL verification** in production
6. **Handle exceptions** properly (HTTPX raises `httpx.HTTPStatusError`, `httpx.RequestError`)

## Error Handling

```python
from app.utils.http_client import CorrelatedHttpClient
import httpx

client = CorrelatedHttpClient(base_url="https://api.example.com")

try:
    response = await client.get("/resource")
    response.raise_for_status()
except httpx.HTTPStatusError as e:
    # HTTP error response (4xx, 5xx)
    logger.error(f"HTTP error: {e.response.status_code}")
except httpx.RequestError as e:
    # Network error, timeout, etc.
    logger.error(f"Request failed: {e}")
```

## Integration with Existing Code

The SSO client (`app/auth/g_sso_client.py`) has been migrated to use `CorrelatedHttpClient`:

```python
# Old implementation
async with httpx.AsyncClient(verify=self.verify_ssl) as client:
    response = await client.post(token_url, data=data, headers=self._get_request_headers())

# New implementation
client = CorrelatedHttpClient(verify_ssl=self.verify_ssl)
response = await client.post(token_url, data=data)
# Correlation ID automatically injected!
```

## Troubleshooting

### Correlation ID Not Being Injected

**Problem**: `X-Request-ID` header is missing from outgoing requests.

**Solution**: 
- Ensure the request is within a request context (handled by `CorrelationIdMiddleware`)
- Check that `context.get_request_id()` returns a valid ID (not `"no-request-id"`)
- Verify middleware is registered in `app/main.py`

### Headers Not Being Preserved

**Problem**: Custom headers are lost when making requests.

**Solution**:
- Pass headers using the `headers` parameter
- The client merges custom headers with correlation ID automatically
- Example: `await client.get(url, headers={"Authorization": "Bearer token"})`

## See Also

- [HTTPX Documentation](https://www.python-httpx.org/)
- [CorrelationIdMiddleware](../../app/middleware.py)
- [Request Context](../../config/context.py)
- [SSO Client Implementation](../../app/auth/g_sso_client.py)
