import contextvars
import uuid
from typing import Optional, Dict, Any

class RequestContext:
    """Manages request-scoped context variables"""
    
    # Context variables - automatically handle async context switching
    request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="no-request-id")
    current_user: contextvars.ContextVar[Optional[Dict]] = contextvars.ContextVar("current_user", default=None)
    
    @classmethod
    def set_request_id(cls, request_id: str) -> contextvars.Token:
        """Set request ID and return token for cleanup"""
        return cls.request_id.set(request_id)
    
    @classmethod
    def get_request_id(cls) -> str:
        """Get current request ID"""
        return cls.request_id.get()
    
    @classmethod
    def set_current_user(cls, user: Optional[Dict]) -> contextvars.Token:
        """Set current user context"""
        return cls.current_user.set(user)
    
    @classmethod
    def get_current_user(cls) -> Optional[Dict]:
        """Get current user from context"""
        return cls.current_user.get()

# Singleton instance
context = RequestContext()