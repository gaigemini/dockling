"""
Example: Token Lifecycle Management for OP (OAuth Provider / Resource Server)

This example demonstrates how a resource server can:
- Use admin tokens for token introspection
- Validate tokens from client applications
- Manage admin token lifecycle automatically
- Build protected API endpoints
"""

import asyncio
import logging
from client.g_sso_client import SimpleSSOClient
from client.token_manager_factory import TokenManagerFactory
from client.managed_http_client import ManagedAPIClient

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# SSO Configuration (Resource Server credentials)
SSO_URL = "http://localhost:8000"
REALM = "master"
RESOURCE_SERVER_CLIENT_ID = "payment-api"
RESOURCE_SERVER_CLIENT_SECRET = "api-secret-456"


async def example_1_token_introspection():
    """
    Example 1: Basic token introspection.
    Resource server validates tokens from client applications.
    """
    print("\n=== Example 1: Token Introspection (Basic) ===\n")
    
    # Resource server needs its own client credentials to call introspect endpoint
    resource_server = SimpleSSOClient(
        sso_url=SSO_URL,
        realm=REALM,
        client_id=RESOURCE_SERVER_CLIENT_ID,
        client_secret=RESOURCE_SERVER_CLIENT_SECRET
    )
    
    # Simulate receiving a token from a client request
    client_token = "sample-token-from-client"  # In reality, from Authorization header
    
    print(f"Validating token: {client_token[:20]}...")
    
    try:
        # Introspect the token
        validation = await resource_server.introspect_token(client_token)
        
        if validation.get("active"):
            print("✓ Token is VALID")
            print(f"  Client ID: {validation.get('client_id')}")
            print(f"  Scope: {validation.get('scope')}")
            print(f"  Token Type: {validation.get('token_type')}")
            print(f"  Expires: {validation.get('exp')}")
            
            # Check if token has required scope
            required_scope = "payment_read"
            token_scopes = validation.get('scope', '').split()
            if required_scope in token_scopes:
                print(f"  ✓ Has required scope: {required_scope}")
            else:
                print(f"  ✗ Missing required scope: {required_scope}")
        else:
            print("✗ Token is INVALID or EXPIRED")
            
    except Exception as e:
        print(f"✗ Introspection failed: {e}")


async def example_2_op_admin_token_lifecycle():
    """
    Example 2: OP admin token with automatic lifecycle management.
    For resource servers that need to call admin APIs frequently.
    """
    print("\n=== Example 2: OP Admin Token Lifecycle ===\n")
    
    # Create admin client (needs admin privileges)
    admin_client = SimpleSSOClient(
        sso_url=SSO_URL,
        realm=REALM,
        client_id="admin-service",
        client_secret="admin-secret-789"
    )
    
    # Create token manager for OP admin operations
    token_manager = TokenManagerFactory.create_op_token_manager(
        sso_client=admin_client,
        cache_key="op_admin_token",
        buffer_seconds=60,
        scope="openid admin",
        max_retries=3
    )
    
    # Get admin token (auto-managed)
    token_data = await token_manager.get_valid_token()
    print(f"✓ Admin token obtained: {token_data.access_token[:20]}...")
    print(f"  Scope: {token_data.scope}")
    
    # Check token info
    info = await token_manager.get_token_info()
    print(f"  Token info: {info}")
    
    # Multiple API calls will use cached token
    print("\nMaking multiple introspection calls (using cached admin token)...")
    for i in range(3):
        print(f"  Call {i+1}: Using token {token_data.access_token[:20]}...")
        # In real scenario: await resource_server.introspect_token(client_token)
    
    print("✓ All calls completed with cached token")


async def example_3_protected_endpoint_middleware():
    """
    Example 3: Building protected API endpoint with token validation.
    Shows how to integrate with FastAPI or similar frameworks.
    """
    print("\n=== Example 3: Protected Endpoint Pattern ===\n")
    
    # Resource server setup
    resource_server = SimpleSSOClient(
        sso_url=SSO_URL,
        realm=REALM,
        client_id=RESOURCE_SERVER_CLIENT_ID,
        client_secret=RESOURCE_SERVER_CLIENT_SECRET
    )
    
    # Simulate FastAPI endpoint handler
    async def protected_api_endpoint(authorization_header: str, required_scope: str = None):
        """
        Simulated protected endpoint.
        In FastAPI, this would be a route handler.
        """
        print(f"\n  Processing request...")
        
        # Extract token from Authorization header
        if not authorization_header.startswith("Bearer "):
            return {"error": "Invalid authorization header", "status": 401}
        
        token = authorization_header.replace("Bearer ", "")
        
        # Validate token via introspection
        try:
            validation = await resource_server.introspect_token(token)
            
            if not validation.get("active"):
                return {"error": "Token is invalid or expired", "status": 401}
            
            # Check scope if required
            if required_scope:
                token_scopes = validation.get('scope', '').split()
                if required_scope not in token_scopes:
                    return {
                        "error": f"Missing required scope: {required_scope}",
                        "status": 403
                    }
            
            # Token is valid, process request
            return {
                "status": 200,
                "message": "Access granted",
                "client_id": validation.get('client_id'),
                "scope": validation.get('scope')
            }
            
        except Exception as e:
            return {"error": f"Token validation failed: {e}", "status": 500}
    
    # Test the endpoint
    print("\nTest 1: Request with valid token")
    result = await protected_api_endpoint(
        authorization_header="Bearer sample-valid-token",
        required_scope="payment_read"
    )
    print(f"  Response: {result}")
    
    print("\nTest 2: Request with missing scope")
    result = await protected_api_endpoint(
        authorization_header="Bearer sample-token",
        required_scope="admin_access"
    )
    print(f"  Response: {result}")


async def example_4_resource_server_with_managed_client():
    """
    Example 4: Resource server using managed client for admin APIs.
    When resource server needs to call other protected services.
    """
    print("\n=== Example 4: Resource Server as Client ===\n")
    
    # Resource server also acts as client to other services
    resource_server = SimpleSSOClient(
        sso_url=SSO_URL,
        realm=REALM,
        client_id=RESOURCE_SERVER_CLIENT_ID,
        client_secret=RESOURCE_SERVER_CLIENT_SECRET
    )
    
    # Create managed client for calling other APIs
    async with TokenManagerFactory.create_managed_api_client(
        sso_client=resource_server,
        api_base_url="http://localhost:8002",  # Another service
        cache_key="resource_server_token",
        scope="notification_send",
        buffer_seconds=60
    ) as api_client:
        
        print("Resource server calling another service...")
        
        try:
            # Token automatically managed and injected
            response = await api_client.post(
                "/api/notifications",
                json={
                    "user_id": "123",
                    "message": "Payment received"
                }
            )
            
            print(f"✓ Response status: {response.status_code}")
            
            if response.is_success:
                data = await response.json()
                print(f"✓ Response: {data}")
            
        except Exception as e:
            print(f"⚠ API call failed: {e}")


async def example_5_token_validation_best_practices():
    """
    Example 5: Best practices for token validation in resource servers.
    """
    print("\n=== Example 5: Token Validation Best Practices ===\n")
    
    resource_server = SimpleSSOClient(
        sso_url=SSO_URL,
        realm=REALM,
        client_id=RESOURCE_SERVER_CLIENT_ID,
        client_secret=RESOURCE_SERVER_CLIENT_SECRET
    )
    
    async def validate_token_with_best_practices(
        authorization_header: str,
        required_scopes: list = None,
        required_client_id: str = None
    ) -> dict:
        """
        Comprehensive token validation with best practices.
        """
        # 1. Extract token
        if not authorization_header or not authorization_header.startswith("Bearer "):
            return {"valid": False, "error": "Missing or invalid authorization header"}
        
        token = authorization_header.replace("Bearer ", "")
        
        # 2. Introspect token
        try:
            validation = await resource_server.introspect_token(token)
        except Exception as e:
            return {"valid": False, "error": f"Introspection failed: {e}"}
        
        # 3. Check if active
        if not validation.get("active"):
            return {"valid": False, "error": "Token is inactive"}
        
        # 4. Check expiration (if provided)
        import time
        exp = validation.get("exp")
        if exp and time.time() > exp:
            return {"valid": False, "error": "Token expired"}
        
        # 5. Check required scopes
        if required_scopes:
            token_scopes = set(validation.get('scope', '').split())
            missing_scopes = set(required_scopes) - token_scopes
            if missing_scopes:
                return {
                    "valid": False,
                    "error": f"Missing scopes: {', '.join(missing_scopes)}"
                }
        
        # 6. Check client ID (if required)
        if required_client_id:
            if validation.get('client_id') != required_client_id:
                return {
                    "valid": False,
                    "error": f"Unauthorized client: {validation.get('client_id')}"
                }
        
        # 7. All checks passed
        return {
            "valid": True,
            "client_id": validation.get('client_id'),
            "scope": validation.get('scope'),
            "token_type": validation.get('token_type')
        }
    
    # Test validation
    print("Testing comprehensive token validation...")
    
    result = await validate_token_with_best_practices(
        authorization_header="Bearer test-token",
        required_scopes=["payment_read", "payment_write"],
        required_client_id="app-a"
    )
    
    if result["valid"]:
        print(f"✓ Token valid")
        print(f"  Client: {result.get('client_id')}")
        print(f"  Scope: {result.get('scope')}")
    else:
        print(f"✗ Token invalid: {result.get('error')}")


async def main():
    """Run all examples"""
    print("=" * 70)
    print("Token Lifecycle Management Examples - OP (OAuth Provider)")
    print("=" * 70)
    
    # Example 1: Basic introspection
    await example_1_token_introspection()
    
    # Example 2: OP admin token lifecycle
    # await example_2_op_admin_token_lifecycle()
    
    # Example 3: Protected endpoint pattern
    # await example_3_protected_endpoint_middleware()
    
    # Example 4: Resource server as client
    # await example_4_resource_server_with_managed_client()
    
    # Example 5: Best practices
    # await example_5_token_validation_best_practices()
    
    print("\n" + "=" * 70)
    print("Examples completed!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
