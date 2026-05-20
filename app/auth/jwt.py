from datetime import datetime, timedelta
from typing import Any, Tuple

from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from jose import ExpiredSignatureError, JWTError, jwt

from app.models.common import CurrentUserModel
from config import get_request_logger, settings

jwt_secret_key = settings.jwt_secret_key
jwt_algorithm = settings.jwt_algorithm
jwt_expire_in = float(settings.jwt_expired_in)

logger = get_request_logger(__name__)


def create_jwt_token(data: dict, expire_in: float = None) -> Tuple[str, float]:
    to_encode = data.copy()
    _expire_in = expire_in if expire_in else jwt_expire_in
    expire = datetime.utcnow() + timedelta(minutes=_expire_in)
    to_encode.update({"exp": expire})
    token = jwt.encode(to_encode, jwt_secret_key, algorithm=jwt_algorithm)
    return token, jwt_expire_in


def decode_jwt_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, jwt_secret_key, algorithms=[jwt_algorithm])


def get_current_user(ctx: Request, token: str = Depends(OAuth2PasswordBearer(tokenUrl="token"))) -> CurrentUserModel:
    def credentials_exception(message: str):
        return HTTPException(
            status_code=401,
            detail=message,
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        credentials = decode_jwt_token(token)
    except ExpiredSignatureError as err:
        logger.error(f"get_current_user - Error: {err}")
        raise credentials_exception("Token already expired.")
    except JWTError as err:
        logger.error(f"get_current_user - Error: {err}")
        raise credentials_exception("Could not validate credentials")

    return CurrentUserModel(
        name=credentials["sub"],
        id=credentials["id"],
        role=credentials["role"],
        auth=credentials["auth"],
        code=credentials["code"],
        token=token,
        request_id=ctx.state.request_id
    )


