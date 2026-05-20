"""SSO-related Pydantic models."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class SsoTokenResponseModel(BaseModel):
    """Response model for SSO token exchange."""
    access_token: str
    token_type: str
    expires_in: int
    refresh_token: Optional[str] = None
    scope: str
    id_token: Optional[str] = None


class SsoUserInfoModel(BaseModel):
    """User information model from SSO provider."""
    sub: str = Field(..., description="Subject identifier (SSO User ID)")
    name: Optional[str] = None
    email: Optional[str] = None
    email_verified: Optional[bool] = None
    phone: Optional[str] = None
    phone_verified: Optional[bool] = None
    attributes: Optional[Dict[str, Any]] = None
    is_enabled: Optional[bool] = None
    is_2fa_enabled: Optional[bool] = None
    roles: List[str] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)
    realm: Optional[str] = None


class SsoIntrospectResponseModel(BaseModel):
    """Response model for token introspection (RFC 7662).

    Standard fields plus additional user claims the SSO may return.
    """
    # Standard RFC 7662 fields
    active: bool
    scope: Optional[str] = None
    client_id: Optional[str] = None
    username: Optional[str] = None
    token_type: Optional[str] = None
    expires_in: Optional[int] = Field(None, alias="exp")
    issued_at: Optional[int] = Field(None, alias="iat")
    subject: Optional[str] = Field(None, alias="sub")

    # Extended user claims (may be present for user tokens)
    name: Optional[str] = None
    email: Optional[str] = None
    email_verified: Optional[bool] = None
    preferred_username: Optional[str] = None
    roles: List[str] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)

    # Additional custom attributes
    attributes: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(populate_by_name=True)
