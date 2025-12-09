from pydantic import BaseModel, Field
from typing import Any, Optional, Literal
from enum import Enum

class OutputType(str, Enum):
    PLAINTEXT = "plaintext"
    MARKDOWN = "markdown"
    HTML = "html"
    CHUNKING = "chunking"

class ChunkType(str, Enum):
    HIERARCHICAL = "hierarchical"
    HYBRID = "hybrid"
    PAGE = "page"

class ProcessingRequest(BaseModel):
    enable_ocr: bool = Field(
        False, description="Enable OCR for scanned documents or images")
    output_type: OutputType = Field(
        OutputType.MARKDOWN, description="Output format type")

class ProcessingResponse(BaseModel):
    success: bool
    message: str
    content: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    processing_time: Optional[float] = None
    metadata: Optional[dict] = None

class ApiResponse(BaseModel):
    """Representation of API response."""
    status: int = Field(description="Status of response, 0 is successfully.")
    message: Optional[str] = Field(
        default=None, description="Explaination of the error.")
    data: Optional[Any] = Field(
        default=None, description="Content of result from API call.")

class ErrorResponse(BaseModel):
    success: bool = False
    error: str
    details: Optional[str] = None