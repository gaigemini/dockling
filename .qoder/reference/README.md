# Token Lifecycle Management

Sistem manajemen token OAuth 2.0 otomatis untuk OP (OAuth Provider) dan RP (Relying Party) dengan fitur:

- ✅ **In-Memory Cache** (single instance)
- ✅ **Redis Cache** (multi-instance/distributed)
- ✅ **Proactive Token Refresh** dengan buffer time
- ✅ **Mutex Lock** untuk mencegah thundering herd problem
- ✅ **HTTP Client Interceptor** untuk transparent token injection
- ✅ **Retry dengan Exponential Backoff**
- ✅ **Clean Architecture** - kode bisnis tidak tercampur logika token

---

## 📁 Struktur File

```
client/
├── g_sso_client.py              # SimpleSSOClient (existing)
├── token_lifecycle.py           # Token lifecycle management core
├── managed_http_client.py       # HTTP client dengan auto token injection
├── token_manager_factory.py     # Factory untuk membuat token managers
├── example_token_lifecycle_rp.py    # Contoh penggunaan untuk RP
├── example_token_lifecycle_op.py    # Contoh penggunaan untuk OP
└── README.md                    # Dokumentasi ini
```

---

## 🎯 Arsitektur

### Alur Token Lifecycle

```
[Kode Bisnis] 
    ↓
[Managed HTTP Client]
    ↓
[Token Lifecycle Manager] → [Cek Cache]
    ↓                           ↓
[Token Valid?] ← No → [Acquire Lock]
    ↓                           ↓
   Yes                    [Fetch New Token]
    ↓                           ↓
[Inject Bearer]           [Save to Cache]
    ↓                           ↓
[API Target] ←───────────── [Return Token]
```

### Komponen Utama

1. **TokenLifecycleManager**: Core manager untuk token lifecycle
2. **TokenCache**: Abstract cache interface
   - `InMemoryTokenCache`: Untuk single instance
   - `RedisTokenCache`: Untuk distributed/multi-instance
3. **ManagedHTTPClient**: HTTP client dengan auto token injection
4. **ManagedAPIClient**: High-level API client dengan response parsing
5. **TokenManagerFactory**: Factory untuk setup mudah

---

## 🚀 Quick Start

### 1. RP (Relying Party) - Client Application

```python
import asyncio
from client import SimpleSSOClient, TokenManagerFactory

async def main():
    # Buat SSO client
    client = SimpleSSOClient(
        sso_url="http://localhost:8000",
        realm="master",
        client_id="app-a",
        client_secret="app-a-secret-123"
    )
    
    # Buat managed API client (token otomatis dikelola)
    async with TokenManagerFactory.create_managed_api_client(
        sso_client=client,
        api_base_url="https://api.example.com",
        scope="payment_read weather_read",
        buffer_seconds=60  # Refresh 60 detik sebelum expired
    ) as api_client:
        
        # Token otomatis di-fetch dan di-inject
        response = await api_client.get("/payments")
        
        if response.is_success:
            data = await response.json()
            print(f"Payments: {data}")

asyncio.run(main())
```

### 2. OP (OAuth Provider) - Resource Server

```python
import asyncio
from client import SimpleSSOClient, TokenManagerFactory

async def validate_token(authorization_header: str):
    """Validasi token dari client"""
    
    # Resource server credentials
    resource_server = SimpleSSOClient(
        sso_url="http://localhost:8000",
        realm="master",
        client_id="payment-api",
        client_secret="api-secret-456"
    )
    
    # Extract token
    token = authorization_header.replace("Bearer ", "")
    
    # Introspect token
    validation = await resource_server.introspect_token(token)
    
    if validation.get("active"):
        print(f"✓ Token valid")
        print(f"  Client: {validation.get('client_id')}")
        print(f"  Scope: {validation.get('scope')}")
        return True
    else:
        print("✗ Token invalid")
        return False
```

---

## 📖 Panduan Lengkap

### A. Token Lifecycle Manager

#### In-Memory Cache (Single Instance)

```python
from client import SimpleSSOClient, TokenManagerFactory

client = SimpleSSOClient(sso_url, realm, client_id, client_secret)

# Token manager dengan in-memory cache
token_manager = TokenManagerFactory.create_rp_token_manager(
    sso_client=client,
    cache_key="my_app_token",
    buffer_seconds=60,  # Refresh 60s sebelum expired
    scope="payment_read"
)

# Get token (auto fetch/refresh)
token_data = await token_manager.get_valid_token()
print(f"Token: {token_data.access_token}")
print(f"Expires in: {token_data.expires_in}s")

# Token info
info = await token_manager.get_token_info()
print(info)

# Force refresh
fresh_token = await token_manager.get_valid_token(force_refresh=True)

# Invalidate (e.g., on logout)
await token_manager.invalidate()
```

#### Redis Cache (Multi-Instance)

```python
from redis.asyncio import Redis
from client import SimpleSSOClient, TokenManagerFactory

# Redis client
redis_client = Redis(host="localhost", port=6379, decode_responses=True)

# Redis cache
redis_cache = TokenManagerFactory.create_redis_cache(
    redis_client=redis_client,
    key_prefix="sso_token:"
)

# SSO client
client = SimpleSSOClient(sso_url, realm, client_id, client_secret)

# Token manager dengan Redis cache
token_manager = TokenManagerFactory.create_rp_token_manager(
    sso_client=client,
    cache=redis_cache,
    cache_key="distributed_token",
    buffer_seconds=60,
    scope="payment_read"
)

# Token akan di-cache di Redis (shared across instances)
token_data = await token_manager.get_valid_token()
```

---

### B. Managed HTTP Client

#### Basic Usage

```python
from client import SimpleSSOClient, TokenManagerFactory

client = SimpleSSOClient(sso_url, realm, client_id, client_secret)

# Managed HTTP client
async with TokenManagerFactory.create_managed_http_client(
    sso_client=client,
    api_base_url="https://api.example.com",
    scope="read write",
    buffer_seconds=60
) as http_client:
    
    # Token otomatis di-inject ke header
    response = await http_client.get("/users")
    print(response.status_code)
    print(response.json())
    
    # POST request
    response = await http_client.post(
        "/users",
        json={"name": "John", "email": "john@example.com"}
    )
    
    # PUT/PATCH/DELETE juga tersedia
    response = await http_client.put("/users/123", json={"name": "Jane"})
    response = await http_client.delete("/users/123")
```

#### High-Level API Client

```python
from client import SimpleSSOClient, TokenManagerFactory

client = SimpleSSOClient(sso_url, realm, client_id, client_secret)

# Managed API client (dengan response parsing)
async with TokenManagerFactory.create_managed_api_client(
    sso_client=client,
    api_base_url="https://api.example.com",
    scope="read write"
) as api_client:
    
    response = await api_client.get("/users")
    
    if response.is_success:
        data = await response.json()
        print(f"Users: {data}")
    else:
        print(f"Error: {response.status_code}")
```

---

### C. OP (Resource Server) - Token Validation

#### Basic Introspection

```python
from client import SimpleSSOClient

resource_server = SimpleSSOClient(
    sso_url="http://localhost:8000",
    realm="master",
    client_id="payment-api",
    client_secret="api-secret-456"
)

# Validate token dari client
async def validate_request(authorization_header: str):
    token = authorization_header.replace("Bearer ", "")
    validation = await resource_server.introspect_token(token)
    
    if validation.get("active"):
        return {
            "valid": True,
            "client_id": validation.get("client_id"),
            "scope": validation.get("scope")
        }
    return {"valid": False}
```

#### Admin Token Management

```python
from client import SimpleSSOClient, TokenManagerFactory

# Admin client
admin_client = SimpleSSOClient(
    sso_url="http://localhost:8000",
    realm="master",
    client_id="admin-service",
    client_secret="admin-secret-789"
)

# OP token manager (untuk admin APIs)
op_token_manager = TokenManagerFactory.create_op_token_manager(
    sso_client=admin_client,
    cache_key="op_admin_token",
    scope="openid admin",
    buffer_seconds=60
)

# Get admin token (auto-managed)
admin_token = await op_token_manager.get_valid_token()
```

---

### D. Best Practices

#### 1. Protected Endpoint Pattern (FastAPI)

```python
from fastapi import FastAPI, Header, HTTPException
from client import SimpleSSOClient

app = FastAPI()
resource_server = SimpleSSOClient(sso_url, realm, client_id, client_secret)

@app.get("/api/payments")
async def get_payments(authorization: str = Header(...)):
    # Validate token
    token = authorization.replace("Bearer ", "")
    validation = await resource_server.introspect_token(token)
    
    if not validation.get("active"):
        raise HTTPException(status_code=401, detail="Invalid token")
    
    # Check scope
    if "payment_read" not in validation.get("scope", "").split():
        raise HTTPException(status_code=403, detail="Insufficient scope")
    
    # Process request
    return {"message": "Access granted", "data": []}
```

#### 2. Comprehensive Validation

```python
async def validate_token_comprehensive(
    authorization_header: str,
    required_scopes: list = None,
    required_client_id: str = None
) -> dict:
    """Validasi token dengan best practices"""
    
    # 1. Extract token
    if not authorization_header.startswith("Bearer "):
        return {"valid": False, "error": "Invalid header"}
    
    token = authorization_header.replace("Bearer ", "")
    
    # 2. Introspect
    validation = await resource_server.introspect_token(token)
    
    # 3. Check active
    if not validation.get("active"):
        return {"valid": False, "error": "Token inactive"}
    
    # 4. Check expiration
    import time
    exp = validation.get("exp")
    if exp and time.time() > exp:
        return {"valid": False, "error": "Token expired"}
    
    # 5. Check scopes
    if required_scopes:
        token_scopes = set(validation.get('scope', '').split())
        if not set(required_scopes).issubset(token_scopes):
            return {"valid": False, "error": "Missing scopes"}
    
    # 6. Check client ID
    if required_client_id:
        if validation.get('client_id') != required_client_id:
            return {"valid": False, "error": "Unauthorized client"}
    
    return {"valid": True, **validation}
```

#### 3. Concurrent Requests (Thundering Herd Prevention)

```python
import asyncio
from client import SimpleSSOClient, TokenManagerFactory

client = SimpleSSOClient(sso_url, realm, client_id, client_secret)

token_manager = TokenManagerFactory.create_rp_token_manager(
    sso_client=client,
    cache_key="concurrent_token",
    buffer_seconds=60
)

# 100 concurrent requests - hanya 1 token fetch terjadi
async def make_request(request_id: int):
    token = await token_manager.get_valid_token()
    # Token sama untuk semua request (mutex lock)
    return token.access_token

tasks = [make_request(i) for i in range(100)]
results = await asyncio.gather(*tasks)

# Semua dapat token yang sama
unique_tokens = set(results)
print(f"Unique tokens: {len(unique_tokens)}")  # Output: 1
```

---

## ⚙️ Konfigurasi

### Buffer Time

```python
# Refresh token 60 detik sebelum expired (default)
token_manager = TokenManagerFactory.create_rp_token_manager(
    sso_client=client,
    buffer_seconds=60  # Adjust based on your needs
)
```

### Retry Configuration

```python
# Retry dengan exponential backoff
token_manager = TokenManagerFactory.create_rp_token_manager(
    sso_client=client,
    max_retries=3,  # Maximum 3 retries
    # Backoff: 1s, 2s, 4s
)
```

### Custom Cache

```python
from client import InMemoryTokenCache, RedisTokenCache

# In-memory (default)
cache = InMemoryTokenCache()

# Redis (untuk distributed)
redis_cache = RedisTokenCache(redis_client, key_prefix="my_app:")

token_manager = TokenManagerFactory.create_rp_token_manager(
    sso_client=client,
    cache=cache
)
```

---

## 🔒 Security Best Practices

1. **Jangan hardcode credentials** - Gunakan environment variables
   ```python
   import os
   client_id = os.getenv("SSO_CLIENT_ID")
   client_secret = os.getenv("SSO_CLIENT_SECRET")
   ```

2. **Gunakan HTTPS** di production
   ```python
   client = SimpleSSOClient(
       sso_url="https://sso.example.com",  # HTTPS!
       ...
   )
   ```

3. **Set verify_ssl=True** di production
   ```python
   client.verify_ssl = True  # Default False untuk development
   ```

4. **Gunakan scope yang spesifik** - Principle of least privilege
   ```python
   scope="payment_read"  # Bukan scope terlalu luas
   ```

5. **Monitor token failures** - Implement circuit breaker jika auth server down

---

## 📊 Flow Diagrams

### Token Refresh Flow

```
Request arrives
    ↓
Check cache
    ↓
Token exists and not expiring? ───Yes──→ Return cached token
    ↓ No
Acquire lock
    ↓
Check cache again (double-checked locking)
    ↓
Token refreshed by another request? ─Yes─→ Return cached token
    ↓ No
Fetch new token from Auth Server
    ↓
Save to cache
    ↓
Return new token
```

### HTTP Request Flow

```
API call
    ↓
Get valid token (auto refresh if needed)
    ↓
Inject Bearer token into headers
    ↓
Execute HTTP request
    ↓
401 Unauthorized? ──Yes──→ Invalidate cache
    ↓                           ↓
   No                      Force refresh token
    ↓                           ↓
Return response          Retry with new token
                              ↓
                         Return response
```

---

## 🧪 Examples

Jalankan contoh lengkap:

```bash
# RP examples
python -m client.example_token_lifecycle_rp

# OP examples
python -m client.example_token_lifecycle_op
```

---

## 🔍 Troubleshooting

### Token selalu di-fetch ulang

- Cek `buffer_seconds` - mungkin terlalu besar
- Pastikan cache bekerja (cek Redis jika menggunakan distributed cache)

### 401 Unauthorized

- Token mungkin invalid di server side
- Cek credentials (client_id, client_secret)
- Cek scope yang diminta

### Redis connection error

- Pastikan Redis running
- Cek konfigurasi host/port
- System akan fallback ke local lock

### Concurrent token fetches

- Pastikan menggunakan `TokenLifecycleManager` (bukan manual fetch)
- Mutex lock akan mencegah multiple fetches

---

## 📚 API Reference

### TokenData

```python
@dataclass
class TokenData:
    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 3600
    refresh_token: Optional[str] = None
    scope: Optional[str] = None
    obtained_at: float
    
    # Properties
    expires_at: float
    is_expired: bool
    
    # Methods
    is_expiring_soon(buffer_seconds: int) -> bool
    to_dict() -> Dict
    from_dict(data: Dict) -> TokenData
    from_oauth_response(response: Dict) -> TokenData
```

### TokenLifecycleManager

```python
class TokenLifecycleManager:
    async def get_valid_token(force_refresh: bool = False) -> TokenData
    async def invalidate()
    async def get_token_info() -> Dict
```

### ManagedHTTPClient

```python
class ManagedHTTPClient:
    async def get(url: str, **kwargs) -> httpx.Response
    async def post(url: str, **kwargs) -> httpx.Response
    async def put(url: str, **kwargs) -> httpx.Response
    async def patch(url: str, **kwargs) -> httpx.Response
    async def delete(url: str, **kwargs) -> httpx.Response
```

### ManagedAPIClient

```python
class ManagedAPIClient:
    async def get(url: str, **kwargs) -> APIResponse
    async def post(url: str, **kwargs) -> APIResponse
    # ... same methods
```

---

## 🤝 Support

Untuk pertanyaan atau issue, silakan buat issue di repository.

---

**Happy coding! 🚀**
