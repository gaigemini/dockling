"""Error response model for API error serialization."""

from typing import Optional

from pydantic import BaseModel


class ErrorResponseModel(BaseModel):
    """Model for serializing error responses."""
    success: bool = False
    error: str
    details: Optional[str] = None
