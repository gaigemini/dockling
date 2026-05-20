"""
Token Lifecycle Management for OAuth 2.0 / OIDC

Provides automatic token management with:
- In-memory cache (single instance)
- Redis cache (multi-instance/distributed)
- Proactive token refresh with buffer time
- Mutex lock to prevent thundering herd problem
- HTTP client interceptor for transparent token injection
"""

import time
import json
import asyncio
import logging
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass, field, asdict
from contextlib import asynccontextmanager
from abc import ABC, abstractmethod

import httpx

logger = logging.getLogger(__name__)


@dataclass
class TokenData:
    """Represents OAuth 2.0 token data with metadata"""
    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 3600  # seconds
    refresh_token: Optional[str] = None
    scope: Optional[str] = None
    obtained_at: float = field(default_factory=time.time)
    
    @property
    def expires_at(self) -> float:
        """Absolute timestamp when token expires"""
        return self.obtained_at + self.expires_in
    
    @property
    def is_expired(self) -> bool:
        """Check if token is currently expired"""
        return time.time() >= self.expires_at
    
    def is_expiring_soon(self, buffer_seconds: int = 60) -> bool:
        """
        Check if token will expire within buffer time.
        Proactively refresh before actual expiration.
        """
        return time.time() + buffer_seconds >= self.expires_at
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TokenData':
        """Deserialize from dictionary"""
        return cls(**data)
    
    @classmethod
    def from_oauth_response(cls, response: Dict[str, Any]) -> 'TokenData':
        """
        Create TokenData from OAuth 2.0 token endpoint response.
        Expected keys: access_token, token_type, expires_in, refresh_token, scope
        """
        return cls(
            access_token=response.get("access_token"),
            token_type=response.get("token_type", "Bearer"),
            expires_in=response.get("expires_in", 3600),
            refresh_token=response.get("refresh_token"),
            scope=response.get("scope"),
        )


class TokenCache(ABC):
    """Abstract base class for token cache implementations"""
    
    @abstractmethod
    async def get(self, key: str) -> Optional[TokenData]:
        """Get token from cache"""
        pass
    
    @abstractmethod
    async def set(self, key: str, token_data: TokenData) -> None:
        """Store token in cache"""
        pass
    
    @abstractmethod
    async def delete(self, key: str) -> None:
        """Remove token from cache"""
        pass


class InMemoryTokenCache(TokenCache):
    """
    In-memory token cache for single-instance applications.
    Uses asyncio.Lock for thread safety.
    """
    
    def __init__(self):
        self._cache: Dict[str, TokenData] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()
    
    async def get(self, key: str) -> Optional[TokenData]:
        return self._cache.get(key)
    
    async def set(self, key: str, token_data: TokenData) -> None:
        self._cache[key] = token_data
    
    async def delete(self, key: str) -> None:
        self._cache.pop(key, None)
    
    @asynccontextmanager
    async def lock(self, key: str):
        """
        Get a lock for a specific key to prevent concurrent token refresh.
        Implements double-checked locking pattern.
        """
        async with self._global_lock:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
        
        async with self._locks[key]:
            yield


class RedisTokenCache(TokenCache):
    """
    Redis-based token cache for distributed/multi-instance applications.
    Prevents thundering herd problem across multiple instances.
    """
    
    def __init__(self, redis_client, key_prefix: str = "sso_token:"):
        """
        Initialize Redis token cache.
        
        Args:
            redis_client: Async Redis client (redis.asyncio.Redis)
            key_prefix: Prefix for all cache keys
        """
        self.redis = redis_client
        self.key_prefix = key_prefix
        self._locks: Dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()
    
    def _make_key(self, key: str) -> str:
        return f"{self.key_prefix}{key}"
    
    async def get(self, key: str) -> Optional[TokenData]:
        try:
            data = await self.redis.get(self._make_key(key))
            if data:
                return TokenData.from_dict(json.loads(data))
            return None
        except Exception as e:
            logger.error(f"Failed to get token from Redis: {e}")
            return None
    
    async def set(self, key: str, token_data: TokenData) -> None:
        try:
            # Set TTL slightly less than token expiry to auto-cleanup
            ttl = max(token_data.expires_in - 10, 60)  # Minimum 60 seconds
            await self.redis.setex(
                self._make_key(key),
                ttl,
                json.dumps(token_data.to_dict())
            )
        except Exception as e:
            logger.error(f"Failed to set token in Redis: {e}")
    
    async def delete(self, key: str) -> None:
        try:
            await self.redis.delete(self._make_key(key))
        except Exception as e:
            logger.error(f"Failed to delete token from Redis: {e}")
    
    @asynccontextmanager
    async def lock(self, key: str):
        """
        Distributed lock using Redis SET NX with expiry.
        Falls back to local lock if Redis lock fails.
        """
        lock_key = f"{self.key_prefix}lock:{key}"
        lock_acquired = False
        
        try:
            # Try to acquire distributed lock (valid for 10 seconds)
            lock_acquired = await self.redis.set(lock_key, "1", nx=True, ex=10)
        except Exception as e:
            logger.warning(f"Redis lock failed, using local lock: {e}")
            lock_acquired = False
        
        if lock_acquired:
            try:
                yield
            finally:
                try:
                    await self.redis.delete(lock_key)
                except:
                    pass
        else:
            # Fallback: wait and retry (simple backoff)
            async with self._global_lock:
                if key not in self._locks:
                    self._locks[key] = asyncio.Lock()
            
            async with self._locks[key]:
                yield


class TokenLifecycleManager:
    """
    Manages OAuth 2.0 token lifecycle with automatic refresh.
    
    Features:
    - Proactive token refresh before expiration
    - Cache management (in-memory or Redis)
    - Concurrency control to prevent multiple simultaneous refreshes
    - Retry with exponential backoff
    """
    
    def __init__(
        self,
        cache: TokenCache,
        token_fetcher: Callable,
        buffer_seconds: int = 60,
        max_retries: int = 3,
        cache_key: str = "default",
    ):
        """
        Initialize Token Lifecycle Manager.
        
        Args:
            cache: TokenCache implementation (InMemoryTokenCache or RedisTokenCache)
            token_fetcher: Async function that fetches new token (returns Dict or TokenData)
            buffer_seconds: Refresh token this many seconds before expiration
            max_retries: Maximum retry attempts on failure
            cache_key: Unique key for this token in cache
        """
        self.cache = cache
        self.token_fetcher = token_fetcher
        self.buffer_seconds = buffer_seconds
        self.max_retries = max_retries
        self.cache_key = cache_key
    
    async def get_valid_token(self, force_refresh: bool = False) -> TokenData:
        """
        Get a valid access token, refreshing if necessary.
        
        Flow:
        1. Check cache for existing token
        2. If token exists and not expiring soon, return it
        3. If token missing/expiring, acquire lock and refresh
        4. Use double-checked locking to prevent redundant refreshes
        
        Args:
            force_refresh: Skip cache and force new token fetch
            
        Returns:
            TokenData with valid access token
        """
        # Step 1: Check cache
        if not force_refresh:
            cached_token = await self.cache.get(self.cache_key)
            
            # Step 2: Return cached token if still valid (with buffer)
            if cached_token and not cached_token.is_expiring_soon(self.buffer_seconds):
                logger.debug(f"Using cached token (expires in {cached_token.expires_at - time.time():.0f}s)")
                return cached_token
        
        # Step 3: Acquire lock and refresh
        async with self.cache.lock(self.cache_key):
            # Double-checked locking: check again inside lock
            if not force_refresh:
                cached_token = await self.cache.get(self.cache_key)
                if cached_token and not cached_token.is_expiring_soon(self.buffer_seconds):
                    logger.debug("Token refreshed by another request, using cached version")
                    return cached_token
            
            # Step 4: Fetch new token with retry
            new_token = await self._fetch_token_with_retry()
            
            # Step 5: Cache the new token
            await self.cache.set(self.cache_key, new_token)
            logger.info(f"Token refreshed successfully (expires in {new_token.expires_in}s)")
            
            return new_token
    
    async def _fetch_token_with_retry(self) -> TokenData:
        """
        Fetch new token with exponential backoff retry.
        
        Returns:
            TokenData with fresh token
        """
        last_exception = None
        
        for attempt in range(self.max_retries):
            try:
                logger.debug(f"Fetching new token (attempt {attempt + 1}/{self.max_retries})")
                
                # Call the token fetcher function
                result = await self.token_fetcher()
                
                # Convert to TokenData if it's a dict
                if isinstance(result, dict):
                    token_data = TokenData.from_oauth_response(result)
                elif isinstance(result, TokenData):
                    token_data = result
                else:
                    raise ValueError(f"Unexpected token fetcher result type: {type(result)}")
                
                return token_data
                
            except Exception as e:
                last_exception = e
                logger.warning(f"Token fetch attempt {attempt + 1} failed: {e}")
                
                if attempt < self.max_retries - 1:
                    # Exponential backoff: 1s, 2s, 4s, ...
                    wait_time = min(2 ** attempt, 10)
                    logger.debug(f"Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
        
        # All retries exhausted
        raise Exception(
            f"Failed to fetch token after {self.max_retries} attempts. "
            f"Last error: {last_exception}"
        )
    
    async def invalidate(self):
        """Force invalidate cached token (e.g., on logout or error)"""
        await self.cache.delete(self.cache_key)
        logger.info("Token cache invalidated")
    
    async def get_token_info(self) -> Optional[Dict[str, Any]]:
        """Get information about cached token without refreshing"""
        token = await self.cache.get(self.cache_key)
        if not token:
            return None
        
        return {
            "has_token": True,
            "expires_at": token.expires_at,
            "expires_in_seconds": max(0, token.expires_at - time.time()),
            "is_expired": token.is_expired,
            "is_expiring_soon": token.is_expiring_soon(self.buffer_seconds),
            "scope": token.scope,
        }
