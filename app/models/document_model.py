"""Document processing models and enums."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class OutputType(str, Enum):
    """Output format type for document conversion."""
    PLAINTEXT = "plaintext"
    MARKDOWN = "markdown"
    HTML = "html"
    CHUNKING = "chunking"


class ChunkType(str, Enum):
    """Chunking strategy type."""
    HIERARCHICAL = "hierarchical"
    HYBRID = "hybrid"
    PAGE = "page"


class ProcessingRequestModel(BaseModel):
    """Request model for document processing."""
    enable_ocr: bool = Field(
        False, description="Enable OCR for scanned documents or images")
    output_type: OutputType = Field(
        OutputType.MARKDOWN, description="Output format type")


class ProcessingResponseModel(BaseModel):
    """Response model for document processing."""
    success: bool
    message: str
    content: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    processing_time: Optional[float] = None
    metadata: Optional[dict] = None


class UploadStatusEnum(str, Enum):
    """Upload session status."""
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class UploadSessionModel(BaseModel):
    """Upload session tracking model."""
    upload_id: str = Field(..., description="Unique upload identifier")
    filename: str = Field(..., description="Original filename")
    safe_filename: str = Field(..., description="Sanitized filename on disk")
    file_path: str = Field("", description="Path to the assembled file")
    total_size: int = Field(..., description="Total file size in bytes")
    received_size: int = Field(0, description="Bytes received so far")
    status: UploadStatusEnum = Field(UploadStatusEnum.IN_PROGRESS)
    mime_type: Optional[str] = Field(None, description="Detected MIME type")
    created_at: float = Field(default_factory=lambda: __import__('time').time())
    updated_at: float = Field(default_factory=lambda: __import__('time').time())

    @property
    def progress(self) -> float:
        """Upload progress as percentage."""
        if self.total_size == 0:
            return 100.0
        return round((self.received_size / self.total_size) * 100, 1)

    @property
    def is_complete(self) -> bool:
        """Check if all bytes received."""
        return self.received_size >= self.total_size
