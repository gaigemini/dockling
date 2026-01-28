from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from .context import context
from .loader import settings
from .logger import get_request_logger

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    request: Request = None
):
    """Validates token and sets user context"""
    logger = get_request_logger("auth")
    
    # Bypass auth in test environment if configured
    if settings.DISABLE_AUTH:
        user = {"id": 999, "username": "docling-user", "is_admin": True}
        context.set_current_user(user)
        return user
    
    try:
        # Simple token validation for docling app
        # In a real app, you would validate against your auth system
        if token == settings.SECRET_KEY:
            user = {"id": 100, "username": "authenticated-user", "is_admin": False}
            context.set_current_user(user)
            return user
        else:
            raise Exception("Invalid token")
            
    except Exception as e:
        logger.error(f"Auth failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )

def get_request_logger_dep(request: Request):
    """Dependency to get request-scoped logger"""
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