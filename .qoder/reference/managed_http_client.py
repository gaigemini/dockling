"""
HTTP Client with Automatic Token Management

Provides:
- AsyncHTTPClient: Drop-in replacement for httpx.AsyncClient with auto token injection
- Token injection interceptor for seamless API calls
- Automatic token refresh on 401 responses
"""

import logging
from typing import Optional, Dict, Any, Union
from contextlib import asynccontextmanager

import httpx

from .token_lifecycle import TokenLifecycleManager, TokenData

logger = logging.getLogger(__name__)


class ManagedHTTPClient:
    """
    HTTP client with automatic OAuth 2.0 token lifecycle management.
    
    Usage:
        # Create token manager
        token_manager = TokenLifecycleManager(
            cache=InMemoryTokenCache(),
            token_fetcher=lambda: client.get_m2m_token(),
            cache_key="my_api_token"
        )
        
        # Create managed client
        async with ManagedHTTPClient(token_manager, base_url="https://api.example.com") as http_client:
            # Token is automatically injected and refreshed
            response = await http_client.get("/users")
    """
    
    def __init__(
        self,
        token_manager: TokenLifecycleManager,
        base_url: str = None,
        max_retries: int = 1,
        **client_kwargs
    ):
        """
        Initialize managed HTTP client.
        
        Args:
            token_manager: TokenLifecycleManager instance
            base_url: Base URL for API requests
            max_retries: Number of retries on 401 (default: 1 retry after token refresh)
            **client_kwargs: Additional arguments passed to httpx.AsyncClient
        """
        self.token_manager = token_manager
        self.base_url = base_url
        self.max_retries = max_retries
        self.client_kwargs = client_kwargs
        self._client: Optional[httpx.AsyncClient] = None
    
    async def __aenter__(self):
        await self._ensure_client()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
    
    async def _ensure_client(self):
        """Create httpx client if not exists"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                **self.client_kwargs
            )
    
    async def close(self):
        """Close the underlying HTTP client"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
    
    def _build_headers(
        self,
        headers: Optional[Dict[str, str]] = None,
        token: Optional[str] = None
    ) -> Dict[str, str]:
        """Build request headers with Bearer token"""
        result = headers.copy() if headers else {}
        
        if token:
            result["Authorization"] = f"Bearer {token}"
        
        return result
    
    async def _request_with_token(
        self,
        method: str,
        url: str,
        retries: int = 0,
        **kwargs
    ) -> httpx.Response:
        """
        Execute HTTP request with automatic token management.
        
        Flow:
        1. Get valid token (refresh if needed)
        2. Inject Bearer token into headers
        3. Execute request
        4. If 401 and retries remaining, refresh token and retry
        """
        await self._ensure_client()
        
        # Get valid token
        token_data = await self.token_manager.get_valid_token()
        
        # Inject token into headers
        kwargs["headers"] = self._build_headers(
            kwargs.get("headers"),
            token=token_data.access_token
        )
        
        # Execute request
        response = await self._client.request(method, url, **kwargs)
        
        # Handle 401 - token might be invalid/expired on server side
        if response.status_code == 401 and retries < self.max_retries:
            logger.warning("Received 401, refreshing token and retrying")
            
            # Force invalidate cache and get fresh token
            await self.token_manager.invalidate()
            token_data = await self.token_manager.get_valid_token(force_refresh=True)
            
            # Update headers with new token
            kwargs["headers"] = self._build_headers(
                kwargs.get("headers"),
                token=token_data.access_token
            )
            
            # Retry request
            response = await self._client.request(method, url, **kwargs)
        
        return response
    
    async def get(self, url: str, **kwargs) -> httpx.Response:
        """HTTP GET request with automatic token injection"""
        return await self._request_with_token("GET", url, **kwargs)
    
    async def post(self, url: str, **kwargs) -> httpx.Response:
        """HTTP POST request with automatic token injection"""
        return await self._request_with_token("POST", url, **kwargs)
    
    async def put(self, url: str, **kwargs) -> httpx.Response:
        """HTTP PUT request with automatic token injection"""
        return await self._request_with_token("PUT", url, **kwargs)
    
    async def patch(self, url: str, **kwargs) -> httpx.Response:
        """HTTP PATCH request with automatic token injection"""
        return await self._request_with_token("PATCH", url, **kwargs)
    
    async def delete(self, url: str, **kwargs) -> httpx.Response:
        """HTTP DELETE request with automatic token injection"""
        return await self._request_with_token("DELETE", url, **kwargs)
    
    async def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Generic HTTP request with automatic token injection"""
        return await self._request_with_token(method.upper(), url, **kwargs)


class APIResponse:
    """
    Helper class to handle API responses with automatic parsing.
    """
    
    def __init__(self, response: httpx.Response):
        self.response = response
        self.status_code = response.status_code
        self._json_cache = None
    
    @property
    def is_success(self) -> bool:
        """Check if request was successful (2xx)"""
        return 200 <= self.status_code < 300
    
    @property
    def is_error(self) -> bool:
        """Check if request failed (4xx or 5xx)"""
        return self.status_code >= 400
    
    async def json(self) -> Any:
        """Parse response as JSON"""
        if self._json_cache is None:
            self._json_cache = self.response.json()
        return self._json_cache
    
    async def text(self) -> str:
        """Get response as text"""
        return self.response.text
    
    def raise_for_status(self):
        """Raise exception if request failed"""
        if self.is_error:
            self.response.raise_for_status()
    
    def __repr__(self):
        return f"<APIResponse {self.status_code}>"


class ManagedAPIClient:
    """
    High-level API client with automatic token management and response parsing.
    
    This is a cleaner interface that returns parsed responses.
    Usage:
        api_client = ManagedAPIClient(token_manager, base_url="https://api.example.com")
        
        async with api_client as client:
            users = await client.get("/users")
            if users.is_success:
                data = await users.json()
    """
    
    def __init__(
        self,
        token_manager: TokenLifecycleManager,
        base_url: str = None,
        **client_kwargs
    ):
        self._http_client = ManagedHTTPClient(
            token_manager=token_manager,
            base_url=base_url,
            **client_kwargs
        )
    
    async def __aenter__(self):
        await self._http_client.__aenter__()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._http_client.__aexit__(exc_type, exc_val, exc_tb)
    
    async def get(self, url: str, **kwargs) -> APIResponse:
        """HTTP GET with automatic token injection and response parsing"""
        response = await self._http_client.get(url, **kwargs)
        return APIResponse(response)
    
    async def post(self, url: str, **kwargs) -> APIResponse:
        """HTTP POST with automatic token injection and response parsing"""
        response = await self._http_client.post(url, **kwargs)
        return APIResponse(response)
    
    async def put(self, url: str, **kwargs) -> APIResponse:
        """HTTP PUT with automatic token injection and response parsing"""
        response = await self._http_client.put(url, **kwargs)
        return APIResponse(response)
    
    async def patch(self, url: str, **kwargs) -> APIResponse:
        """HTTP PATCH with automatic token injection and response parsing"""
        response = await self._http_client.patch(url, **kwargs)
        return APIResponse(response)
    
    async def delete(self, url: str, **kwargs) -> APIResponse:
        """HTTP DELETE with automatic token injection and response parsing"""
        response = await self._http_client.delete(url, **kwargs)
        return APIResponse(response)
