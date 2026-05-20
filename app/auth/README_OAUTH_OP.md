# OAuth OP Implementation - Simple & Stateless

## Overview

Docling API acts as a **Resource Server (OP)** that validates tokens from client applications using SSO introspection.

## Architecture

```
Client App ──Bearer Token──> Docling API ──Introspect──> SSO Server
                     ↓                                    ↓
              Validate Token                    http://127.0.0.1:1877
                     ↓                             /api/v1/auth/GAI
              Grant/Deny Access                   /introspect
```

## How It Works (Simple Flow)

### 1. Client Makes Request

```bash
curl -X POST http://localhost:8000/api/v1/convert \
  -H "Authorization: Bearer <token>" \
  -F "file=@document.pdf"
```

### 2. Token Validation (Automatic)

Located in `app/dependencies/auth.py`:

```python
async def get_current_user(token: str) -> CurrentUserModel:
    # 1. Extract Bearer token from header
    # 2. Call SSO introspection
    introspect = await sso_service.introspect_token(token)
    
    # 3. Check if token is active
    if not introspect.active:
        raise HTTPException(401, "Token invalid")
    
    # 4. Return user model
    return CurrentUserModel(...)
```

### 3. SSO Introspection

Located in `app/auth/g_sso_client.py`:

```python
async def introspect_token(self, token: str) -> Dict:
    """Validate token via SSO introspection endpoint"""
    introspect_url = f"{self.sso_url}/api/v1/auth/{self.realm}/introspect"
    
    data = {
        "token": token,
        "client_id": self.client_id,
        "client_secret": self.client_secret
    }
    
    response = await client.post(introspect_url, data=data)
    return response.json()  # {"active": True, "scope": "...", ...}
```

## Configuration

### Environment Variables

```bash
# In env/dev.env
SSO_URL=http://127.0.0.1:1877
SSO_REALM=GAI
SSO_CLIENT_ID=icode
SSO_CLIENT_SECRET=<your-secret>  # Required for introspection
```

### Default Values

Defined in `config/base.py`:

```python
SSO_URL: str = "http://127.0.0.1:1877"
SSO_REALM: str = "GAI"
SSO_CLIENT_ID: str = "icode"
SSO_CLIENT_SECRET: Optional[str] = None
```

## Files Structure

### Core Files (Keep)

```
app/auth/
├── g_sso_client.py      # SSO client with introspect_token()
├── sso_service.py       # Service layer for SSO operations
└── jwt.py               # JWT utilities (if needed)

app/dependencies/
└── auth.py              # Token validation dependency

app/models/
└── sso_model.py         # Pydantic models for SSO responses
```

### Deleted Files (Not Needed for OP)

❌ `token_lifecycle.py` - For clients managing tokens
❌ `managed_http_client.py` - For clients calling APIs
❌ `token_manager_factory.py` - For client token management
❌ `example_op_oauth.py` - Unnecessary complexity

## Key Points

### What OP Does ✅
- **Validate tokens** via introspection on every request
- **Check token status** (active/inactive)
- **Extract user info** from introspection response
- **Grant or deny access** based on token validity

### What OP Does NOT Do ❌
- **Store tokens** - Tokens are stateless
- **Cache tokens** - Validate real-time every request
- **Manage token lifecycle** - Client's responsibility
- **Refresh tokens** - Client handles refresh

## Testing

### Check Configuration

```bash
./bin/python -c "from config import settings; print(settings.SSO_URL)"
```

### Test with Real Token

```bash
# Get token from SSO server first
# Then test the API
curl -X GET http://localhost:8000/api/v1/convert \
  -H "Authorization: Bearer <your-token>"
```

### Disable Auth for Testing

In `env/dev.env`:
```bash
DISABLE_AUTH=true
```

## Error Handling

| Scenario | Status Code | Response |
|----------|-------------|----------|
| Missing token | 401 | Missing authentication token |
| Invalid token | 401 | Token is invalid or expired |
| SSO down | 503 | Authentication service unavailable |

## Security Best Practices

1. **Set SSO_CLIENT_SECRET** - Required for introspection
2. **Use HTTPS in production** - `SSO_URL=https://...`
3. **Enable SSL verification** - Set `verify_ssl = True` in production
4. **Rotate secrets regularly** - Update `SSO_CLIENT_SECRET`
5. **Monitor SSO availability** - 503 errors indicate SSO issues

## Next Steps

1. ✅ Configuration complete (`SSO_URL=http://127.0.0.1:1877`)
2. ✅ Realm configured (`SSO_REALM=GAI`)
3. ⏳ Set `SSO_CLIENT_SECRET` environment variable
4. ⏳ Ensure SSO server is running
5. ⏳ Test with real token from SSO

## Summary

**Simple, stateless, and correct!**

- No token storage
- No token caching
- No lifecycle management
- Just introspect and validate on every request

This is the **correct pattern for Resource Servers (OP)**.
