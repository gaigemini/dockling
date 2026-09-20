"""Document processing models and enums."""

import time
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class OutputType(str, Enum):
    """Output format type for document conversion."""
    PLAINTEXT = "plaintext"
    MARKDOWN = "markdown"
    HTML = "html"


class ImageMode(str, Enum):
    """Image reference mode for markdown export.

    Controls how images are referenced in the output markdown.
    """
    EMBEDDED = "embedded"       # Images embedded as base64 data URIs
    REFERENCED = "referenced"   # Images referenced by file path
    PLACEHOLDER = "placeholder"  # Placeholder text instead of images


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


class ChunkTextRequestModel(BaseModel):
    """Request model for chunking raw markdown/text content (no file upload)."""
    content: str = Field(..., description="Markdown or text content to process")
    filename: Optional[str] = Field("document.md", description="Virtual filename (used for format detection)")
    max_tokens: int = Field(512, ge=1, description="Maximum tokens per chunk")
    chunk_type: ChunkType = Field(ChunkType.HYBRID, description="Chunking strategy")
    output_type: OutputType = Field(OutputType.MARKDOWN, description="Output format for conversion")
    generate_picture_images: bool = Field(False, description="Extract and embed images from PDF documents")
    generate_table_images: bool = Field(False, description="Generate table images alongside structure")
    table_mode: Optional[str] = Field(None, pattern="^(fast|accurate)$", description="TableFormer mode: 'fast' or 'accurate' (default)")
    image_mode: Optional[ImageMode] = Field(None, description="Image reference mode: embedded, referenced, placeholder")
    from_page: Optional[int] = Field(None, ge=1, description="Start page (1-based, inclusive)")
    to_page: Optional[int] = Field(None, ge=1, description="End page (1-based, inclusive)")


class ConvertTextRequestModel(BaseModel):
    """Request model for converting raw markdown/text content (no file upload)."""
    content: str = Field(..., description="Markdown or text content to convert")
    filename: Optional[str] = Field("document.md", description="Virtual filename (used for format detection)")
    output_type: OutputType = Field(OutputType.MARKDOWN, description="Output format type")
    generate_picture_images: bool = Field(False, description="Extract and embed images from PDF documents")
    generate_table_images: bool = Field(False, description="Generate table images alongside structure")
    table_mode: Optional[str] = Field(None, pattern="^(fast|accurate)$", description="TableFormer mode: 'fast' or 'accurate' (default)")
    image_mode: Optional[ImageMode] = Field(None, description="Image reference mode: embedded, referenced, placeholder")
    from_page: Optional[int] = Field(None, ge=1, description="Start page (1-based, inclusive)")
    to_page: Optional[int] = Field(None, ge=1, description="End page (1-based, inclusive)")


class UploadSessionModel(BaseModel):
    """Upload session tracking model (persisted in Redis)."""
    upload_id: str = Field(..., description="Unique upload identifier")
    filename: str = Field(..., description="Original filename")
    safe_filename: str = Field(..., description="Sanitized, collision-free filename")
    file_path: str = Field("", description="Local scratch path while assembling chunks")
    object_key: str = Field("", description="Object storage key once the upload is completed")
    total_size: int = Field(..., description="Total file size in bytes")
    received_size: int = Field(0, description="Bytes received so far")
    status: UploadStatusEnum = Field(UploadStatusEnum.IN_PROGRESS)
    mime_type: Optional[str] = Field(None, description="Detected MIME type")
    user_id: str = Field("", description="Owner (authenticated user) of this upload session")
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

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
