"""
Generic HTTPX client with automatic correlation ID injection.

This module provides a wrapper around httpx that automatically injects
the current request's correlation ID (X-Request-ID) into all outgoing
HTTP requests, enabling distributed tracing across services.
"""

from typing import Dict, Optional, Any, Union
from contextlib import asynccontextmanager

import httpx

from config.context import context


class HttpClient:
    """
    HTTPX client wrapper that automatically injects correlation IDs.
    
    This client ensures that all outgoing HTTP requests include the
    current request's correlation ID in the X-Request-ID header,
    enabling end-to-end request tracing across microservices.
    """
    
    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[httpx.Timeout] = None,
        verify_ssl: bool = True,
        **kwargs
    ):
        """
        Initialize the correlated HTTP client.
        
        Args:
            base_url: Base URL for all requests
            timeout: HTTPX timeout configuration
            verify_ssl: Whether to verify SSL certificates
            **kwargs: Additional arguments passed to httpx.AsyncClient
        """
        self.base_url = base_url
        self.timeout = timeout or httpx.Timeout(10.0)
        self.verify_ssl = verify_ssl
        self.client_kwargs = kwargs
        
    def _inject_correlation_id(self, headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """
        Inject correlation ID into headers.
        
        Args:
            headers: Existing headers to merge with correlation ID
            
        Returns:
            Headers dict with correlation ID injected
        """
        result_headers = headers.copy() if headers else {}
        
        # Get current request ID from context
        request_id = context.get_request_id()
        if request_id and request_id != "no-request-id":
            result_headers["X-Request-ID"] = request_id
            
        return result_headers
    
    async def get(
        self,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[httpx.Timeout] = None,
        **kwargs
    ) -> httpx.Response:
        """
        Make a GET request with automatic correlation ID injection.
        
        Args:
            url: Request URL
            headers: Optional headers
            params: Optional query parameters
            timeout: Optional timeout override
            **kwargs: Additional arguments passed to httpx
            
        Returns:
            httpx.Response object
        """
        correlated_headers = self._inject_correlation_id(headers)
        
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout or self.timeout,
            verify=self.verify_ssl,
            **self.client_kwargs
        ) as client:
            return await client.get(
                url,
                headers=correlated_headers,
                params=params,
                **kwargs
            )
    
    async def post(
        self,
        url: str,
        *,
        data: Optional[Union[Dict[str, Any], str]] = None,
        json: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[httpx.Timeout] = None,
        **kwargs
    ) -> httpx.Response:
        """
        Make a POST request with automatic correlation ID injection.
        
        Args:
            url: Request URL
            data: Form data
            json: JSON payload
            headers: Optional headers
            params: Optional query parameters
            timeout: Optional timeout override
            **kwargs: Additional arguments passed to httpx
            
        Returns:
            httpx.Response object
        """
        correlated_headers = self._inject_correlation_id(headers)
        
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout or self.timeout,
            verify=self.verify_ssl,
            **self.client_kwargs
        ) as client:
            return await client.post(
                url,
                data=data,
                json=json,
                headers=correlated_headers,
                params=params,
                **kwargs
            )
    
    async def put(
        self,
        url: str,
        *,
        data: Optional[Union[Dict[str, Any], str]] = None,
        json: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[httpx.Timeout] = None,
        **kwargs
    ) -> httpx.Response:
        """
        Make a PUT request with automatic correlation ID injection.
        
        Args:
            url: Request URL
            data: Form data
            json: JSON payload
            headers: Optional headers
            params: Optional query parameters
            timeout: Optional timeout override
            **kwargs: Additional arguments passed to httpx
            
        Returns:
            httpx.Response object
        """
        correlated_headers = self._inject_correlation_id(headers)
        
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout or self.timeout,
            verify=self.verify_ssl,
            **self.client_kwargs
        ) as client:
            return await client.put(
                url,
                data=data,
                json=json,
                headers=correlated_headers,
                params=params,
                **kwargs
            )
    
    async def patch(
        self,
        url: str,
        *,
        data: Optional[Union[Dict[str, Any], str]] = None,
        json: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[httpx.Timeout] = None,
        **kwargs
    ) -> httpx.Response:
        """
        Make a PATCH request with automatic correlation ID injection.
        
        Args:
            url: Request URL
            data: Form data
            json: JSON payload
            headers: Optional headers
            params: Optional query parameters
            timeout: Optional timeout override
            **kwargs: Additional arguments passed to httpx
            
        Returns:
            httpx.Response object
        """
        correlated_headers = self._inject_correlation_id(headers)
        
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout or self.timeout,
            verify=self.verify_ssl,
            **self.client_kwargs
        ) as client:
            return await client.patch(
                url,
                data=data,
                json=json,
                headers=correlated_headers,
                params=params,
                **kwargs
            )
    
    async def delete(
        self,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[httpx.Timeout] = None,
        **kwargs
    ) -> httpx.Response:
        """
        Make a DELETE request with automatic correlation ID injection.
        
        Args:
            url: Request URL
            headers: Optional headers
            params: Optional query parameters
            timeout: Optional timeout override
            **kwargs: Additional arguments passed to httpx
            
        Returns:
            httpx.Response object
        """
        correlated_headers = self._inject_correlation_id(headers)
        
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout or self.timeout,
            verify=self.verify_ssl,
            **self.client_kwargs
        ) as client:
            return await client.delete(
                url,
                headers=correlated_headers,
                params=params,
                **kwargs
            )
    
    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[httpx.Timeout] = None,
        **kwargs
    ) -> httpx.Response:
        """
        Make a generic HTTP request with automatic correlation ID injection.
        
        Args:
            method: HTTP method (GET, POST, PUT, PATCH, DELETE, etc.)
            url: Request URL
            headers: Optional headers
            timeout: Optional timeout override
            **kwargs: Additional arguments passed to httpx
            
        Returns:
            httpx.Response object
        """
        correlated_headers = self._inject_correlation_id(headers)
        
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout or self.timeout,
            verify=self.verify_ssl,
            **self.client_kwargs
        ) as client:
            return await client.request(
                method,
                url,
                headers=correlated_headers,
                **kwargs
            )


@asynccontextmanager
async def get_correlated_client(
    base_url: Optional[str] = None,
    timeout: Optional[httpx.Timeout] = None,
    verify_ssl: bool = True,
    **kwargs
):
    """
    Context manager for creating a correlated HTTP client.
    
    This provides a convenient way to use the correlated client with
    automatic connection pooling and cleanup.
    
    Args:
        base_url: Base URL for all requests
        timeout: HTTPX timeout configuration
        verify_ssl: Whether to verify SSL certificates
        **kwargs: Additional arguments passed to httpx.AsyncClient
        
    Yields:
        HttpClient instance
    """
    client = HttpClient(
        base_url=base_url,
        timeout=timeout,
        verify_ssl=verify_ssl,
        **kwargs
    )
    try:
        yield client
    finally:
        # Client is cleaned up automatically since we create new instances per request
        pass
