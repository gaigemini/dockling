"""
Example usage of CorrelatedHttpClient for making HTTP requests with automatic correlation ID injection.

This module demonstrates how to use the CorrelatedHttpClient wrapper to ensure
all outgoing HTTP requests include the current request's correlation ID.
"""

from app.utils.http_client import HttpClient, get_correlated_client
from config import get_request_logger_dep
from fastapi import Depends, FastAPI
import httpx


app = FastAPI()


# Example 1: Basic usage with GET request
async def example_basic_get():
    """Basic GET request - correlation ID is automatically injected"""
    client = HttpClient(base_url="https://api.example.com")
    response = await client.get("/users/123")
    return response.json()


# Example 2: POST request with JSON payload
async def example_post_with_json():
    """POST request with JSON payload - correlation ID is automatically injected"""
    client = HttpClient(base_url="https://api.example.com")
    response = await client.post(
        "/users",
        json={"name": "John Doe", "email": "john@example.com"}
    )
    return response.json()


# Example 3: Request with custom headers (they are preserved and merged)
async def example_with_custom_headers():
    """Request with custom headers - correlation ID is added to existing headers"""
    client = HttpClient(base_url="https://api.example.com")
    response = await client.get(
        "/protected-resource",
        headers={
            "Authorization": "Bearer my-token",
            "Accept": "application/json"
        }
    )
    return response.json()


# Example 4: Using context manager for connection pooling
async def example_context_manager():
    """Using context manager for better resource management"""
    async with get_correlated_client(base_url="https://api.example.com") as client:
        response = await client.get("/health")
        return response.json()


# Example 5: PUT request
async def example_put_request():
    """PUT request to update a resource"""
    client = HttpClient(base_url="https://api.example.com")
    response = await client.put(
        "/users/123",
        json={"name": "Jane Doe", "email": "jane@example.com"}
    )
    return response.json()


# Example 6: PATCH request
async def example_patch_request():
    """PATCH request for partial updates"""
    client = HttpClient(base_url="https://api.example.com")
    response = await client.patch(
        "/users/123",
        json={"email": "newemail@example.com"}
    )
    return response.json()


# Example 7: DELETE request
async def example_delete_request():
    """DELETE request to remove a resource"""
    client = HttpClient(base_url="https://api.example.com")
    response = await client.delete("/users/123")
    return response.json()


# Example 8: Custom timeout configuration
async def example_custom_timeout():
    """Request with custom timeout settings"""
    custom_timeout = httpx.Timeout(30.0, connect=10.0)
    client = HttpClient(
        base_url="https://api.example.com",
        timeout=custom_timeout
    )
    response = await client.get("/slow-endpoint")
    return response.json()


# Example 9: Disable SSL verification (for development/testing)
async def example_no_ssl_verification():
    """Request with SSL verification disabled (use only in dev/test)"""
    client = HttpClient(
        base_url="https://localhost:8080",
        verify_ssl=False
    )
    response = await client.get("/health")
    return response.json()


# Example 10: Using in a FastAPI endpoint
@app.get("/api/external-data")
async def get_external_data(logger=Depends(get_request_logger_dep)):
    """
    FastAPI endpoint that calls an external service.
    The correlation ID from the incoming request will be automatically
    injected into the outgoing HTTP request.
    """
    logger.info("Fetching external data")
    
    client = HttpClient(base_url="https://api.example.com")
    response = await client.get("/data")
    
    logger.info(f"External data fetched: {response.status_code}")
    return response.json()


# Example 11: Multiple requests in sequence
async def example_multiple_requests():
    """Making multiple requests - each gets the same correlation ID"""
    client = HttpClient(base_url="https://api.example.com")
    
    # All these requests will have the same correlation ID
    users_response = await client.get("/users")
    posts_response = await client.get("/posts")
    comments_response = await client.get("/comments")
    
    return {
        "users": users_response.json(),
        "posts": posts_response.json(),
        "comments": comments_response.json()
    }


# Example 12: Error handling with correlation ID
async def example_error_handling():
    """Error handling - correlation ID is still injected even on errors"""
    client = HttpClient(base_url="https://api.example.com")
    
    try:
        response = await client.get("/nonexistent")
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        # The correlation ID was still injected into the request
        print(f"HTTP error occurred: {e.response.status_code}")
        raise
    except httpx.RequestError as e:
        print(f"Request error occurred: {e}")
        raise
    
    return response.json()


# Example 13: Form data POST
async def example_post_form_data():
    """POST request with form data instead of JSON"""
    client = HttpClient(base_url="https://api.example.com")
    response = await client.post(
        "/submit-form",
        data={"field1": "value1", "field2": "value2"}
    )
    return response.json()


# Example 14: Request with query parameters
async def example_with_query_params():
    """GET request with query parameters"""
    client = HttpClient(base_url="https://api.example.com")
    response = await client.get(
        "/search",
        params={"q": "search term", "page": 1, "limit": 10}
    )
    return response.json()


# Example 15: Generic request method for any HTTP method
async def example_generic_request():
    """Using the generic request method for any HTTP method"""
    client = HttpClient(base_url="https://api.example.com")
    
    # OPTIONS request
    response = await client.request("OPTIONS", "/resource")
    
    # HEAD request
    head_response = await client.request("HEAD", "/resource")
    
    return {
        "options": response.headers,
        "head": head_response.headers
    }
