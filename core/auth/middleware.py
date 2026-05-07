"""JWT middleware and require_role FastAPI dependency."""

from typing import Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError

from core.auth.jwt_utils import decode_access_token

_bearer = HTTPBearer(auto_error=True)


class TokenPayload:
    def __init__(self, payload: dict):
        self.sub: str = payload["sub"]
        self.tenant_id: str = payload["tenant_id"]
        self.role: str = payload["role"]
        self.jti: str = payload.get("jti", "")
        self.raw = payload


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> TokenPayload:
    token = credentials.credentials
    try:
        payload = decode_access_token(token)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return TokenPayload(payload)


def require_role(*roles: str) -> Callable:
    """FastAPI dependency factory — enforces role membership."""

    async def _check(user: TokenPayload = Depends(get_current_user)) -> TokenPayload:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role}' not permitted. Required: {roles}",
            )
        return user

    return _check
