"""SSO-based authentication dependency using token introspection (M2M).

This application acts as a Resource Server (Resource Provider):
- Every API call must include a Bearer token in the Authorization header
- The token is verified against the SSO provider via introspect_token()
- If valid, the introspection response populates the CurrentUserModel
- The current user is stored in the request context
"""

from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer

from app.auth.sso_service import sso_service
from app.models.common import CurrentUserModel
from config import get_request_logger, settings
from config.context import context

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)


async def get_current_user(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
) -> CurrentUserModel:
    """Validate Bearer token via SSO introspection and return current user.

    Flow:
    1. Extract Bearer token from Authorization header
    2. If DISABLE_AUTH is enabled, return a mock user (for testing)
    3. Call SSO introspect_token to validate
    4. If active=True, create CurrentUserModel from introspection response
    5. If active=False, raise 401 Unauthorized
    """
    logger = get_request_logger("auth")

    # --- Step 1: Bypass auth for test environment ---
    if settings.DISABLE_AUTH:
        mock_user = CurrentUserModel(
            name="docling-user",
            id="999",
            role=["admin"],
            auth="bypass",
            code="bypass",
            token="",
            preferred_username="docling-user",
            request_id=context.get_request_id(),
        )
        context.set_current_user({
            "id": "999",
            "username": "docling-user",
            "is_admin": True,
            "name": "docling-user",
        })
        return mock_user

    # --- Step 2: Extract Bearer token ---
    if not token:
        # Fallback: try extracting directly from header
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]

    if not token:
        logger.warning("Missing Bearer token in request")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # --- Step 3: Introspect token against SSO ---
    try:
        introspect = await sso_service.introspect_token(token)
    except Exception as e:
        logger.error(f"Token introspection call failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable",
        )

    # --- Step 4: Validate active status ---
    if not introspect.active:
        logger.warning(f"Token is not active (expired or revoked)")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is invalid or expired",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # --- Step 5: Build CurrentUserModel from introspection response ---
    # For M2M tokens: sub=client_id, username=client_name, scope=permissions
    user_id = introspect.subject or introspect.client_id or "unknown"
    user_name = introspect.name or introspect.preferred_username or introspect.username or user_id

    # Parse scope into role list
    roles = list(introspect.roles)
    if not roles and introspect.scope:
        roles = [s.strip() for s in introspect.scope.split() if s.strip()]
    if not roles:
        roles = ["machine"]

    current_user = CurrentUserModel(
        name=user_name,
        id=user_id,
        role=roles,
        auth=introspect.token_type or "Bearer",
        code=introspect.client_id or "",
        token=token,
        email=introspect.email,
        preferred_username=introspect.preferred_username,
        request_id=context.get_request_id(),
    )

    # Store as dict for backward-compatible context access
    context.set_current_user({
        "id": user_id,
        "username": user_name,
        "name": user_name,
        "email": introspect.email,
        "roles": roles,
        "client_id": introspect.client_id,
        "token_type": introspect.token_type,
    })

    logger.info(f"Authenticated user: {user_name} (id={user_id})")
    return current_user
