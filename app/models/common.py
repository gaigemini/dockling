"""Common models shared across the application."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class CurrentUserModel(BaseModel):
    """Current authenticated user model."""
    name: str
    id: str
    role: list[str]
    auth: str
    code: str
    token: str
    email: Optional[str] = None
    preferred_username: Optional[str] = None
    request_id: Optional[str] = None


class LogInfoModel(BaseModel):
    """Representation of Logging for information."""
    request_id: Optional[str] = Field(
        default=None, description="Logging id of process flow.")
    info: Optional[Any] = Field(
        default=None, description="Content of logging information.")


class LogErrorModel(BaseModel):
    """Representation of Logging for error."""
    request_id: str = Field(description="Logging id of process flow.")
    error_id: int = Field(description="Error id.")
    error: Any = Field(description="Error description.")


class ProcessStatusModel(BaseModel):
    """Status of process."""
    status: int = Field(description="Status of response, 0 is successfully.")
    message: Optional[str] = Field(
        default=None, description="Explaination of the status process.")


class BaseMessageModel(BaseModel):
    """Representation of a base message model."""
    id: Optional[str] = Field(description="Primary key")
    channel_id: str = Field(description="Channel id, like whatsapp number.")
    channel: str = Field(description="Is channel where the chat is come from.")
    subchannel: Optional[str] = Field(
        default=None, description="Is additional information of the channel.")
    channelref: Optional[str] = Field(
        default=None, description="Is reference for the channel.")
    service_id: str = Field(
        description="Is service id where the chat is come from.")