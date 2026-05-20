"""
Token Management Factory

Provides easy-to-use factory methods to create:
- OP (OAuth Provider) token managers for resource servers
- RP (Relying Party) token managers for client applications
- Complete managed HTTP clients with all configurations
"""

import logging
from typing import Optional, Any

from .g_sso_client import SimpleSSOClient
from .token_lifecycle import (
    TokenLifecycleManager,
    TokenCache,
    InMemoryTokenCache,
    RedisTokenCache,
)
from .managed_http_client import ManagedHTTPClient, ManagedAPIClient

logger = logging.getLogger(__name__)


class TokenManagerFactory:
    """
    Factory for creating OAuth 2.0 token lifecycle managers.
    
    Supports both:
    - OP (OAuth Provider): Token introspection and validation for resource servers
    - RP (Relying Party): M2M token acquisition for client applications
    """
    
    @staticmethod
    def create_in_memory_cache() -> InMemoryTokenCache:
        """Create in-memory token cache (single instance)"""
        return InMemoryTokenCache()
    
    @staticmethod
    def create_redis_cache(
        redis_client: Any,
        key_prefix: str = "sso_token:"
    ) -> RedisTokenCache:
        """
        Create Redis-based token cache (distributed/multi-instance).
        
        Args:
            redis_client: Async Redis client instance
            key_prefix: Prefix for cache keys
        """
        return RedisTokenCache(redis_client, key_prefix)
    
    @classmethod
    def create_rp_token_manager(
        cls,
        sso_client: SimpleSSOClient,
        cache: Optional[TokenCache] = None,
        cache_key: str = "rp_m2m_token",
        buffer_seconds: int = 60,
        max_retries: int = 3,
        scope: Optional[str] = None,
    ) -> TokenLifecycleManager:
        """
        Create token manager for RP (Relying Party) - Client applications.
        
        Use this when your application needs to call other services using M2M tokens.
        
        Args:
            sso_client: Configured SimpleSSOClient instance
            cache: Token cache (creates InMemoryTokenCache if None)
            cache_key: Unique cache key for this token
            buffer_seconds: Refresh token before expiration (seconds)
            max_retries: Maximum retry attempts
            scope: OAuth scope to request
            
        Returns:
            TokenLifecycleManager configured for M2M token acquisition
        """
        if cache is None:
            cache = cls.create_in_memory_cache()
        
        async def fetch_m2m_token():
            """Token fetcher function for M2M flow"""
            logger.debug(f"Fetching M2M token for client: {sso_client.client_id}")
            token_response = await sso_client.get_m2m_token(scope=scope)
            return token_response
        
        return TokenLifecycleManager(
            cache=cache,
            token_fetcher=fetch_m2m_token,
            buffer_seconds=buffer_seconds,
            max_retries=max_retries,
            cache_key=cache_key,
        )
    
    @classmethod
    def create_op_token_manager(
        cls,
        sso_client: SimpleSSOClient,
        cache: Optional[TokenCache] = None,
        cache_key: str = "op_admin_token",
        buffer_seconds: int = 60,
        max_retries: int = 3,
        scope: str = "openid admin",
    ) -> TokenLifecycleManager:
        """
        Create token manager for OP (OAuth Provider) - Resource servers / Admin APIs.
        
        Use this when your service needs admin-level tokens for token introspection
        or managing OAuth resources.
        
        Args:
            sso_client: Configured SimpleSSOClient instance (with admin credentials)
            cache: Token cache (creates InMemoryTokenCache if None)
            cache_key: Unique cache key for this token
            buffer_seconds: Refresh token before expiration (seconds)
            max_retries: Maximum retry attempts
            scope: OAuth scope to request (default: admin scope)
            
        Returns:
            TokenLifecycleManager configured for admin/OP token acquisition
        """
        if cache is None:
            cache = cls.create_in_memory_cache()
        
        async def fetch_op_token():
            """Token fetcher function for OP admin flow"""
            logger.debug(f"Fetching OP admin token for client: {sso_client.client_id}")
            token_response = await sso_client.get_m2m_token(scope=scope)
            return token_response
        
        return TokenLifecycleManager(
            cache=cache,
            token_fetcher=fetch_op_token,
            buffer_seconds=buffer_seconds,
            max_retries=max_retries,
            cache_key=cache_key,
        )
    
    @classmethod
    def create_managed_http_client(
        cls,
        sso_client: SimpleSSOClient,
        cache: Optional[TokenCache] = None,
        cache_key: str = "managed_token",
        buffer_seconds: int = 60,
        max_retries: int = 3,
        scope: Optional[str] = None,
        api_base_url: str = None,
        **httpx_kwargs
    ) -> ManagedHTTPClient:
        """
        Create complete managed HTTP client with automatic token management.
        
        This is the recommended approach for most use cases.
        
        Args:
            sso_client: Configured SimpleSSOClient instance
            cache: Token cache (creates InMemoryTokenCache if None)
            cache_key: Unique cache key for this token
            buffer_seconds: Refresh token before expiration (seconds)
            max_retries: Maximum retry attempts
            scope: OAuth scope to request
            api_base_url: Base URL for API requests
            **httpx_kwargs: Additional arguments for httpx.AsyncClient
            
        Returns:
            ManagedHTTPClient with automatic token lifecycle management
            
        Example:
            async with create_managed_http_client(
                sso_client=client,
                api_base_url="https://api.example.com",
                scope="payment_read"
            ) as http_client:
                response = await http_client.get("/payments")
        """
        token_manager = cls.create_rp_token_manager(
            sso_client=sso_client,
            cache=cache,
            cache_key=cache_key,
            buffer_seconds=buffer_seconds,
            max_retries=max_retries,
            scope=scope,
        )
        
        return ManagedHTTPClient(
            token_manager=token_manager,
            base_url=api_base_url,
            **httpx_kwargs
        )
    
    @classmethod
    def create_managed_api_client(
        cls,
        sso_client: SimpleSSOClient,
        cache: Optional[TokenCache] = None,
        cache_key: str = "managed_api_token",
        buffer_seconds: int = 60,
        max_retries: int = 3,
        scope: Optional[str] = None,
        api_base_url: str = None,
        **httpx_kwargs
    ) -> ManagedAPIClient:
        """
        Create high-level API client with automatic token management.
        
        Similar to create_managed_http_client but returns parsed responses.
        
        Args:
            sso_client: Configured SimpleSSOClient instance
            cache: Token cache (creates InMemoryTokenCache if None)
            cache_key: Unique cache key for this token
            buffer_seconds: Refresh token before expiration (seconds)
            max_retries: Maximum retry attempts
            scope: OAuth scope to request
            api_base_url: Base URL for API requests
            **httpx_kwargs: Additional arguments for httpx.AsyncClient
            
        Returns:
            ManagedAPIClient with automatic token lifecycle management
            
        Example:
            async with create_managed_api_client(
                sso_client=client,
                api_base_url="https://api.example.com",
                scope="weather_read"
            ) as api_client:
                response = await api_client.get("/weather")
                if response.is_success:
                    data = await response.json()
        """
        token_manager = cls.create_rp_token_manager(
            sso_client=sso_client,
            cache=cache,
            cache_key=cache_key,
            buffer_seconds=buffer_seconds,
            max_retries=max_retries,
            scope=scope,
        )
        
        return ManagedAPIClient(
            token_manager=token_manager,
            base_url=api_base_url,
            **httpx_kwargs
        )
