"""
Example: Token Lifecycle Management for RP (Relying Party)

This example demonstrates how a client application can automatically
manage M2M tokens with:
- In-memory caching (single instance)
- Redis caching (multi-instance/distributed)
- Automatic token refresh before expiration
- HTTP client with transparent token injection
"""

import asyncio
import logging
from client.g_sso_client import SimpleSSOClient
from client.token_lifecycle import InMemoryTokenCache, RedisTokenCache
from client.token_manager_factory import TokenManagerFactory
from client.managed_http_client import ManagedHTTPClient, ManagedAPIClient

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# SSO Configuration
SSO_URL = "http://localhost:8000"
REALM = "master"
CLIENT_ID = "app-a"
CLIENT_SECRET = "app-a-secret-123"

# Target API to call
API_BASE_URL = "http://localhost:8001"


async def example_1_basic_token_management():
    """
    Example 1: Basic token lifecycle management with in-memory cache.
    Suitable for single-instance applications.
    """
    print("\n=== Example 1: Basic Token Management (In-Memory) ===\n")
    
    # Create SSO client
    sso_client = SimpleSSOClient(
        sso_url=SSO_URL,
        realm=REALM,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET
    )
    
    # Create token manager with in-memory cache
    token_manager = TokenManagerFactory.create_rp_token_manager(
        sso_client=sso_client,
        cache_key="example_1_token",
        buffer_seconds=60,  # Refresh 60 seconds before expiration
        scope="payment_read weather_read"
    )
    
    # Get valid token (automatically fetches or refreshes)
    token_data = await token_manager.get_valid_token()
    print(f"✓ Token obtained: {token_data.access_token[:20]}...")
    print(f"  Expires in: {token_data.expires_in} seconds")
    print(f"  Scope: {token_data.scope}")
    
    # Get token info
    info = await token_manager.get_token_info()
    print(f"  Token info: {info}")
    
    # Second call will use cached token
    print("\nSecond call (should use cache):")
    token_data2 = await token_manager.get_valid_token()
    print(f"✓ Token from cache: {token_data2.access_token[:20]}...")
    
    # Force refresh
    print("\nForce refresh:")
    token_data3 = await token_manager.get_valid_token(force_refresh=True)
    print(f"✓ Fresh token: {token_data3.access_token[:20]}...")
    
    # Invalidate token (e.g., on logout)
    await token_manager.invalidate()
    print("✓ Token invalidated")


async def example_2_redis_cache():
    """
    Example 2: Token management with Redis cache.
    Suitable for multi-instance/distributed applications.
    """
    print("\n=== Example 2: Token Management with Redis Cache ===\n")
    
    try:
        from redis.asyncio import Redis
        
        # Create Redis client
        redis_client = Redis(
            host="localhost",
            port=6379,
            db=0,
            decode_responses=True
        )
        
        # Test Redis connection
        await redis_client.ping()
        print("✓ Redis connected")
        
        # Create SSO client
        sso_client = SimpleSSOClient(
            sso_url=SSO_URL,
            realm=REALM,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET
        )
        
        # Create token manager with Redis cache
        redis_cache = TokenManagerFactory.create_redis_cache(
            redis_client=redis_client,
            key_prefix="sso_token:"
        )
        
        token_manager = TokenManagerFactory.create_rp_token_manager(
            sso_client=sso_client,
            cache=redis_cache,
            cache_key="example_2_token",
            buffer_seconds=60,
            scope="payment_read"
        )
        
        # Get token (stored in Redis)
        token_data = await token_manager.get_valid_token()
        print(f"✓ Token obtained and cached in Redis: {token_data.access_token[:20]}...")
        
        # Verify it's in Redis
        info = await token_manager.get_token_info()
        print(f"✓ Token info: {info}")
        
        await redis_client.close()
        
    except Exception as e:
        print(f"⚠ Redis not available (skip this example): {e}")


async def example_3_managed_http_client():
    """
    Example 3: HTTP client with automatic token injection.
    Token is automatically attached to every request and refreshed when needed.
    """
    print("\n=== Example 3: Managed HTTP Client ===\n")
    
    # Create SSO client
    sso_client = SimpleSSOClient(
        sso_url=SSO_URL,
        realm=REALM,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET
    )
    
    # Create managed HTTP client using factory
    async with TokenManagerFactory.create_managed_http_client(
        sso_client=sso_client,
        api_base_url=API_BASE_URL,
        cache_key="example_3_token",
        scope="payment_read",
        buffer_seconds=60
    ) as http_client:
        
        print("Making API request (token auto-injected)...")
        
        try:
            # Token is automatically fetched and injected
            response = await http_client.get("/api/payments")
            print(f"✓ Response status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"✓ Response data: {data}")
            
        except Exception as e:
            print(f"⚠ API call failed: {e}")


async def example_4_managed_api_client():
    """
    Example 4: High-level API client with response parsing.
    Clean interface for application code.
    """
    print("\n=== Example 4: Managed API Client (High-Level) ===\n")
    
    # Create SSO client
    sso_client = SimpleSSOClient(
        sso_url=SSO_URL,
        realm=REALM,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET
    )
    
    # Create managed API client
    async with TokenManagerFactory.create_managed_api_client(
        sso_client=sso_client,
        api_base_url=API_BASE_URL,
        cache_key="example_4_token",
        scope="weather_read",
        buffer_seconds=60
    ) as api_client:
        
        print("Making API request with high-level client...")
        
        try:
            response = await api_client.get("/api/weather")
            print(f"✓ Response status: {response.status_code}")
            print(f"✓ Is success: {response.is_success}")
            
            if response.is_success:
                data = await response.json()
                print(f"✓ Parsed data: {data}")
            
        except Exception as e:
            print(f"⚠ API call failed: {e}")


async def example_5_concurrent_requests():
    """
    Example 5: Concurrent requests with mutex lock.
    Demonstrates how the lock prevents multiple simultaneous token refreshes.
    """
    print("\n=== Example 5: Concurrent Requests (Mutex Lock) ===\n")
    
    # Create SSO client
    sso_client = SimpleSSOClient(
        sso_url=SSO_URL,
        realm=REALM,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET
    )
    
    # Create token manager
    token_manager = TokenManagerFactory.create_rp_token_manager(
        sso_client=sso_client,
        cache_key="example_5_token",
        buffer_seconds=60,
        scope="payment_read"
    )
    
    # Force invalidate to trigger refresh
    await token_manager.invalidate()
    
    # Simulate 10 concurrent requests
    async def make_request(request_id: int):
        print(f"  Request {request_id}: Getting token...")
        token = await token_manager.get_valid_token()
        print(f"  Request {request_id}: Token obtained {token.access_token[:20]}...")
        return token
    
    print("Launching 10 concurrent requests...")
    tasks = [make_request(i) for i in range(1, 11)]
    results = await asyncio.gather(*tasks)
    
    # All requests should get the same token (only 1 refresh happened)
    unique_tokens = set(t.access_token for t in results)
    print(f"\n✓ All requests completed")
    print(f"  Unique tokens: {len(unique_tokens)} (should be 1)")
    print(f"  All got same token: {len(unique_tokens) == 1}")


async def main():
    """Run all examples"""
    print("=" * 70)
    print("Token Lifecycle Management Examples - RP (Relying Party)")
    print("=" * 70)
    
    # Example 1: Basic token management
    await example_1_basic_token_management()
    
    # Example 2: Redis cache (optional, skip if Redis not available)
    # await example_2_redis_cache()
    
    # Example 3: Managed HTTP client
    # await example_3_managed_http_client()
    
    # Example 4: Managed API client
    # await example_4_managed_api_client()
    
    # Example 5: Concurrent requests
    # await example_5_concurrent_requests()
    
    print("\n" + "=" * 70)
    print("Examples completed!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
