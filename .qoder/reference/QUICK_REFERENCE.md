# Quick Reference - Token Lifecycle Management

## Import Statements

```python
from client import (
    SimpleSSOClient,
    TokenManagerFactory,
    InMemoryTokenCache,
    RedisTokenCache,
    ManagedHTTPClient,
    ManagedAPIClient,
)
```

---

## Quick Setup

### 1. RP (Relying Party) - Client App

```python
from client import SimpleSSOClient, TokenManagerFactory

# Setup
client = SimpleSSOClient(sso_url, realm, client_id, client_secret)

# Option A: Managed API Client (Recommended)
async with TokenManagerFactory.create_managed_api_client(
    sso_client=client,
    api_base_url="https://api.example.com",
    scope="read write"
) as api_client:
    response = await api_client.get("/resource")
    data = await response.json()

# Option B: Token Manager Only
token_manager = TokenManagerFactory.create_rp_token_manager(
    sso_client=client,
    scope="read"
)
token = await token_manager.get_valid_token()
```

### 2. OP (Resource Server) - Token Validation

```python
from client import SimpleSSOClient

# Setup
resource_server = SimpleSSOClient(sso_url, realm, client_id, client_secret)

# Validate token
async def validate_request(authorization_header: str):
    token = authorization_header.replace("Bearer ", "")
    validation = await resource_server.introspect_token(token)
    
    if validation.get("active"):
        return True  # Token valid
    return False  # Token invalid
```

---

## Common Patterns

### Pattern 1: Multiple API Calls

```python
async with TokenManagerFactory.create_managed_api_client(
    sso_client=client,
    api_base_url="https://api.example.com",
    scope="payment_read"
) as api_client:
    
    # Token managed automatically
    payments = await api_client.get("/payments")
    user = await api_client.get("/users/123")
    report = await api_client.post("/reports", json={"type": "monthly"})
```

### Pattern 2: Redis Cache (Distributed)

```python
from redis.asyncio import Redis

redis_client = Redis(host="localhost", port=6379, decode_responses=True)
redis_cache = TokenManagerFactory.create_redis_cache(redis_client)

async with TokenManagerFactory.create_managed_api_client(
    sso_client=client,
    cache=redis_cache,
    api_base_url="https://api.example.com"
) as api_client:
    response = await api_client.get("/data")
```

### Pattern 3: FastAPI Protected Endpoint

```python
from fastapi import FastAPI, Header, HTTPException
from client import SimpleSSOClient

app = FastAPI()
rs = SimpleSSOClient(sso_url, realm, client_id, client_secret)

@app.get("/api/protected")
async def protected_endpoint(authorization: str = Header(...)):
    token = authorization.replace("Bearer ", "")
    validation = await rs.introspect_token(token)
    
    if not validation.get("active"):
        raise HTTPException(status_code=401)
    
    return {"message": "Access granted"}
```

### Pattern 4: Concurrent Requests

```python
import asyncio

token_manager = TokenManagerFactory.create_rp_token_manager(
    sso_client=client,
    cache_key="shared_token"
)

# All concurrent requests share same token (mutex lock)
async def fetch_data(endpoint: str):
    token = await token_manager.get_valid_token()
    # Use token...

tasks = [fetch_data(ep) for ep in endpoints]
await asyncio.gather(*tasks)
```

---

## Configuration Options

```python
TokenManagerFactory.create_rp_token_manager(
    sso_client=client,
    cache=None,                    # Cache instance (default: InMemoryTokenCache)
    cache_key="default",          # Unique cache key
    buffer_seconds=60,            # Refresh before expiry (seconds)
    max_retries=3,                # Retry attempts on failure
    scope=None,                   # OAuth scope to request
)
```

---

## API Methods

### TokenLifecycleManager

```python
# Get valid token (auto refresh if needed)
token = await manager.get_valid_token()

# Force refresh
token = await manager.get_valid_token(force_refresh=True)

# Get token info
info = await manager.get_token_info()

# Invalidate cache
await manager.invalidate()
```

### ManagedAPIClient

```python
# HTTP methods
response = await client.get(url, **kwargs)
response = await client.post(url, **kwargs)
response = await client.put(url, **kwargs)
response = await client.patch(url, **kwargs)
response = await client.delete(url, **kwargs)

# Response handling
if response.is_success:
    data = await response.json()
    text = await response.text()
```

### ManagedHTTPClient

```python
# Returns httpx.Response directly
response = await client.get(url, **kwargs)
print(response.status_code)
print(response.json())
```

---

## Error Handling

```python
try:
    async with TokenManagerFactory.create_managed_api_client(
        sso_client=client,
        api_base_url="https://api.example.com"
    ) as api_client:
        response = await api_client.get("/resource")
        
        if response.is_error:
            print(f"Error: {response.status_code}")
        else:
            data = await response.json()
            
except Exception as e:
    print(f"Request failed: {e}")
```

---

## Environment Variables

```bash
# SSO Configuration
export SSO_URL="http://localhost:8000"
export SSO_REALM="master"
export SSO_CLIENT_ID="my-app"
export SSO_CLIENT_SECRET="secret-123"

# Redis (optional)
export REDIS_HOST="localhost"
export REDIS_PORT=6379
```

```python
import os

client = SimpleSSOClient(
    sso_url=os.getenv("SSO_URL"),
    realm=os.getenv("SSO_REALM"),
    client_id=os.getenv("SSO_CLIENT_ID"),
    client_secret=os.getenv("SSO_CLIENT_SECRET")
)
```

---

## Testing

```bash
# Run unit tests
./bin/python -m pytest tests/unit/test_token_lifecycle.py -v

# Run examples
./bin/python -m client.example_token_lifecycle_rp
./bin/python -m client.example_token_lifecycle_op
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Token always refreshing | Check `buffer_seconds` value |
| 401 Unauthorized | Verify credentials and scope |
| Redis connection error | Check Redis is running |
| Multiple token fetches | Ensure using TokenLifecycleManager |

---

## File Structure

```
client/
├── token_lifecycle.py          # Core token management
├── managed_http_client.py      # HTTP clients
├── token_manager_factory.py    # Factory methods
├── example_token_lifecycle_rp.py   # RP examples
├── example_token_lifecycle_op.py   # OP examples
└── README.md                   # Full documentation
```

---

For detailed documentation, see [README.md](README.md)
