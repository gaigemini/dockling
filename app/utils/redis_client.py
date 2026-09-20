"""Async Redis client singleton for task queue and state management."""

from typing import Optional

import redis.asyncio as aioredis

from config import get_service_logger

_redis_client: Optional[aioredis.Redis] = None
_logger = get_service_logger("redis")


async def init_redis(url: str) -> aioredis.Redis:
    """Initialize the global async Redis connection.

    Args:
        url: Redis connection URL (e.g. ``redis://localhost:6379/0``).

    Returns:
        The shared ``aioredis.Redis`` instance.
    """
    global _redis_client
    if _redis_client is not None:
        return _redis_client

    _redis_client = aioredis.from_url(
        url,
        encoding="utf-8",
        decode_responses=True,
        socket_timeout=30,
        socket_connect_timeout=10,
        retry_on_timeout=True,
    )

    # Verify connectivity
    try:
        await _redis_client.ping()
        _logger.info("Redis connection established", extra={"url": url})
    except Exception as exc:
        _logger.error(f"Redis connection failed: {exc}", exc_info=True)
        await close_redis()
        raise

    return _redis_client


def get_redis() -> aioredis.Redis:
    """Return the shared Redis client.

    Raises:
        RuntimeError: If ``init_redis`` has not been called yet.
    """
    if _redis_client is None:
        raise RuntimeError("Redis client not initialized. Call init_redis() first.")
    return _redis_client


async def close_redis() -> None:
    """Close the shared Redis connection gracefully."""
    global _redis_client
    if _redis_client is not None:
        try:
            await _redis_client.close()
            _logger.info("Redis connection closed")
        except Exception as exc:
            _logger.warning(f"Error closing Redis connection: {exc}")
        finally:
            _redis_client = None


async def check_redis_health() -> bool:
    """Check if Redis is reachable and responding.

    Returns:
        ``True`` if Redis responds to PING, ``False`` otherwise.
    """
    try:
        client = get_redis()
        return bool(await client.ping())
    except Exception:
        return False
