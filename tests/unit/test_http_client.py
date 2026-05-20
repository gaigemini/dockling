"""
Tests for the CorrelatedHttpClient wrapper.

Tests verify that:
1. Correlation IDs are automatically injected into all HTTP requests
2. Existing headers are preserved and merged correctly
3. All HTTP methods (GET, POST, PUT, PATCH, DELETE) work correctly
4. The client works with and without a correlation ID in context
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from contextlib import asynccontextmanager

from config.context import context
from app.utils.http_client import HttpClient, get_correlated_client


class TestHttpClient:
    """Test suite for HttpClient"""

    @pytest.fixture
    def mock_response(self):
        """Create a mock HTTP response"""
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"status": "ok"}
        response.text = '{"status": "ok"}'
        return response

    @pytest.fixture
    def test_correlation_id(self):
        """Set up a test correlation ID"""
        return "test-correlation-id-12345"

    def test_inject_correlation_id_with_context(self, test_correlation_id):
        """Test that correlation ID is injected when present in context"""
        # Set correlation ID in context
        token = context.set_request_id(test_correlation_id)
        
        try:
            client = HttpClient()
            headers = client._inject_correlation_id()
            
            assert "X-Request-ID" in headers
            assert headers["X-Request-ID"] == test_correlation_id
        finally:
            # Clean up context
            context.request_id.reset(token)

    def test_inject_correlation_id_without_context(self):
        """Test that no correlation ID is injected when not in context"""
        # Ensure no correlation ID in context
        token = context.set_request_id("no-request-id")
        
        try:
            client = HttpClient()
            headers = client._inject_correlation_id()
            
            assert "X-Request-ID" not in headers
        finally:
            # Clean up context
            context.request_id.reset(token)

    def test_inject_correlation_id_merges_existing_headers(self, test_correlation_id):
        """Test that existing headers are preserved when injecting correlation ID"""
        # Set correlation ID in context
        token = context.set_request_id(test_correlation_id)
        
        try:
            client = HttpClient()
            existing_headers = {"Authorization": "Bearer token123", "Content-Type": "application/json"}
            headers = client._inject_correlation_id(existing_headers)
            
            assert "X-Request-ID" in headers
            assert headers["X-Request-ID"] == test_correlation_id
            assert headers["Authorization"] == "Bearer token123"
            assert headers["Content-Type"] == "application/json"
        finally:
            # Clean up context
            context.request_id.reset(token)

    @pytest.mark.asyncio
    async def test_get_request_injects_correlation_id(self, test_correlation_id, mock_response):
        """Test GET request includes correlation ID header"""
        token = context.set_request_id(test_correlation_id)
        
        try:
            with patch('app.utils.http_client.httpx.AsyncClient') as MockClient:
                mock_client_instance = AsyncMock()
                mock_client_instance.get.return_value = mock_response
                mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                mock_client_instance.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = mock_client_instance
                
                client = HttpClient(base_url="https://api.example.com")
                await client.get("/test-endpoint", params={"key": "value"})
                
                # Verify the get method was called with correct headers
                mock_client_instance.get.assert_called_once()
                call_kwargs = mock_client_instance.get.call_args[1]
                
                assert "headers" in call_kwargs
                assert call_kwargs["headers"]["X-Request-ID"] == test_correlation_id
        finally:
            context.request_id.reset(token)

    @pytest.mark.asyncio
    async def test_post_request_injects_correlation_id(self, test_correlation_id, mock_response):
        """Test POST request includes correlation ID header"""
        token = context.set_request_id(test_correlation_id)
        
        try:
            with patch('app.utils.http_client.httpx.AsyncClient') as MockClient:
                mock_client_instance = AsyncMock()
                mock_client_instance.post.return_value = mock_response
                mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                mock_client_instance.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = mock_client_instance
                
                client = HttpClient(base_url="https://api.example.com")
                await client.post("/test-endpoint", json={"data": "test"})
                
                # Verify the post method was called with correct headers
                mock_client_instance.post.assert_called_once()
                call_kwargs = mock_client_instance.post.call_args[1]
                
                assert "headers" in call_kwargs
                assert call_kwargs["headers"]["X-Request-ID"] == test_correlation_id
        finally:
            context.request_id.reset(token)

    @pytest.mark.asyncio
    async def test_put_request_injects_correlation_id(self, test_correlation_id, mock_response):
        """Test PUT request includes correlation ID header"""
        token = context.set_request_id(test_correlation_id)
        
        try:
            with patch('app.utils.http_client.httpx.AsyncClient') as MockClient:
                mock_client_instance = AsyncMock()
                mock_client_instance.put.return_value = mock_response
                mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                mock_client_instance.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = mock_client_instance
                
                client = HttpClient(base_url="https://api.example.com")
                await client.put("/test-endpoint", json={"data": "updated"})
                
                # Verify the put method was called with correct headers
                mock_client_instance.put.assert_called_once()
                call_kwargs = mock_client_instance.put.call_args[1]
                
                assert "headers" in call_kwargs
                assert call_kwargs["headers"]["X-Request-ID"] == test_correlation_id
        finally:
            context.request_id.reset(token)

    @pytest.mark.asyncio
    async def test_patch_request_injects_correlation_id(self, test_correlation_id, mock_response):
        """Test PATCH request includes correlation ID header"""
        token = context.set_request_id(test_correlation_id)
        
        try:
            with patch('app.utils.http_client.httpx.AsyncClient') as MockClient:
                mock_client_instance = AsyncMock()
                mock_client_instance.patch.return_value = mock_response
                mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                mock_client_instance.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = mock_client_instance
                
                client = HttpClient(base_url="https://api.example.com")
                await client.patch("/test-endpoint", json={"data": "patched"})
                
                # Verify the patch method was called with correct headers
                mock_client_instance.patch.assert_called_once()
                call_kwargs = mock_client_instance.patch.call_args[1]
                
                assert "headers" in call_kwargs
                assert call_kwargs["headers"]["X-Request-ID"] == test_correlation_id
        finally:
            context.request_id.reset(token)

    @pytest.mark.asyncio
    async def test_delete_request_injects_correlation_id(self, test_correlation_id, mock_response):
        """Test DELETE request includes correlation ID header"""
        token = context.set_request_id(test_correlation_id)
        
        try:
            with patch('app.utils.http_client.httpx.AsyncClient') as MockClient:
                mock_client_instance = AsyncMock()
                mock_client_instance.delete.return_value = mock_response
                mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                mock_client_instance.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = mock_client_instance
                
                client = HttpClient(base_url="https://api.example.com")
                await client.delete("/test-endpoint")
                
                # Verify the delete method was called with correct headers
                mock_client_instance.delete.assert_called_once()
                call_kwargs = mock_client_instance.delete.call_args[1]
                
                assert "headers" in call_kwargs
                assert call_kwargs["headers"]["X-Request-ID"] == test_correlation_id
        finally:
            context.request_id.reset(token)

    @pytest.mark.asyncio
    async def test_request_method_injects_correlation_id(self, test_correlation_id, mock_response):
        """Test generic request method includes correlation ID header"""
        token = context.set_request_id(test_correlation_id)
        
        try:
            with patch('app.utils.http_client.httpx.AsyncClient') as MockClient:
                mock_client_instance = AsyncMock()
                mock_client_instance.request.return_value = mock_response
                mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                mock_client_instance.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = mock_client_instance
                
                client = HttpClient(base_url="https://api.example.com")
                await client.request("OPTIONS", "/test-endpoint")
                
                # Verify the request method was called with correct headers
                mock_client_instance.request.assert_called_once()
                call_args = mock_client_instance.request.call_args
                call_kwargs = call_args[1]
                
                assert "headers" in call_kwargs
                assert call_kwargs["headers"]["X-Request-ID"] == test_correlation_id
        finally:
            context.request_id.reset(token)

    def test_client_initialization_with_custom_timeout(self):
        """Test client can be initialized with custom timeout"""
        import httpx
        custom_timeout = httpx.Timeout(30.0, connect=10.0)
        client = HttpClient(timeout=custom_timeout)
        
        assert client.timeout == custom_timeout

    def test_client_initialization_with_verify_ssl_false(self):
        """Test client can be initialized with SSL verification disabled"""
        client = HttpClient(verify_ssl=False)
        
        assert client.verify_ssl is False

    @pytest.mark.asyncio
    async def test_get_correlated_client_context_manager(self, test_correlation_id):
        """Test the get_correlated_client context manager"""
        token = context.set_request_id(test_correlation_id)
        
        try:
            async with get_correlated_client(base_url="https://api.example.com") as client:
                assert isinstance(client, HttpClient)
                assert client.base_url == "https://api.example.com"
        finally:
            context.request_id.reset(token)

    @pytest.mark.asyncio
    async def test_post_with_existing_headers_preserves_them(self, test_correlation_id, mock_response):
        """Test that POST with existing headers preserves them while adding correlation ID"""
        token = context.set_request_id(test_correlation_id)
        
        try:
            with patch('app.utils.http_client.httpx.AsyncClient') as MockClient:
                mock_client_instance = AsyncMock()
                mock_client_instance.post.return_value = mock_response
                mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                mock_client_instance.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = mock_client_instance
                
                client = HttpClient(base_url="https://api.example.com")
                existing_headers = {
                    "Authorization": "Bearer secret-token",
                    "Content-Type": "application/json"
                }
                await client.post("/test-endpoint", json={"data": "test"}, headers=existing_headers)
                
                # Verify headers were merged correctly
                mock_client_instance.post.assert_called_once()
                call_kwargs = mock_client_instance.post.call_args[1]
                
                assert "headers" in call_kwargs
                headers = call_kwargs["headers"]
                assert headers["X-Request-ID"] == test_correlation_id
                assert headers["Authorization"] == "Bearer secret-token"
                assert headers["Content-Type"] == "application/json"
        finally:
            context.request_id.reset(token)
