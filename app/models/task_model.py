"""Models for async task processing."""

import time
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    """Lifecycle states for an async conversion task."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"   # waited too long in the queue
    TIMEOUT = "timeout"   # exceeded the max processing time


# Terminal states: no further transitions happen and result TTL applies.
TERMINAL_STATUSES = (
    TaskStatus.COMPLETED,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
    TaskStatus.EXPIRED,
    TaskStatus.TIMEOUT,
)


class TaskInfo(BaseModel):
    """Full state of a single async task, persisted in Redis."""
    task_id: str = Field(..., description="Unique task identifier (UUID4)")
    status: TaskStatus = Field(TaskStatus.PENDING, description="Current task state")
    endpoint: str = Field(..., description="Conversion endpoint name (e.g. convert, convert_n_chunk)")
    params: Dict[str, Any] = Field(default_factory=dict, description="Serialized request parameters")
    file_path: Optional[str] = Field(None, description="Legacy local path to the uploaded file (dev fallback)")
    file_key: Optional[str] = Field(None, description="Object storage key of the uploaded input file")
    callback_url: Optional[str] = Field(None, description="Webhook URL notified on terminal status")
    timeout_seconds: Optional[int] = Field(None, description="Per-request max processing time override")
    queue_expires_at: Optional[float] = Field(None, description="Unix timestamp after which a PENDING task is EXPIRED")
    processing_deadline: Optional[float] = Field(None, description="Unix timestamp after which a PROCESSING task is TIMEOUT")
    created_at: float = Field(default_factory=time.time, description="Unix timestamp when task was created")
    started_at: Optional[float] = Field(None, description="Unix timestamp when processing started")
    completed_at: Optional[float] = Field(None, description="Unix timestamp when processing finished")
    result: Optional[Dict[str, Any]] = Field(None, description="Deprecated: legacy inline result (results now live in object storage)")
    result_ref: Optional[str] = Field(None, description="Object storage key of the result artifact (JSON)")
    result_summary: Optional[Dict[str, Any]] = Field(None, description="Small summary of the result artifact")
    error: Optional[str] = Field(None, description="Error message (on failure)")

    @property
    def processing_time(self) -> Optional[float]:
        """Total processing time in seconds (only when completed)."""
        if self.started_at and self.completed_at:
            return round(self.completed_at - self.started_at, 2)
        return None

    @property
    def is_terminal(self) -> bool:
        """True when the task has reached a final state."""
        return self.status in TERMINAL_STATUSES


class TaskSubmitResponse(BaseModel):
    """Response returned immediately when a task is submitted."""
    task_id: str = Field(..., description="Unique task identifier")
    status: str = Field(TaskStatus.PENDING.value, description="Initial task status")
    message: str = Field(
        "Task submitted successfully. Poll the status URL or wait for the callback.",
        description="Human-readable message",
    )
    poll_url: str = Field(..., description="URL to poll for task status")
    result_url: str = Field(..., description="URL to fetch the result artifact once completed")
    callback_url: Optional[str] = Field(None, description="Webhook URL that will be notified on terminal status")
