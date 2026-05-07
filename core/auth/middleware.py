from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError
from core.auth.jwt_utils import decode_access_token

_bearer = HTTPBearer(auto_error=False)
ROLE_HIERARCHY = {"viewer": 0, "engineer": 1, "admin": 2}


class TokenPayload:
    """Compatibility shim for routers that expect TokenPayload."""
    def __init__(self, payload: dict):
        self.sub: str = payload.get("sub", "")
        self.user_id: str = payload.get("user_id", "")
        self.tenant_id: str = payload.get("tenant_id", "")
        self.role: str = payload.get("role", "")
        self.raw = payload


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(_bearer)) -> dict:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        return decode_access_token(credentials.credentials)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

def require_role(*roles: str):
    """Accept either a minimum role (hierarchy check) or an explicit set of allowed roles."""
    def dependency(user: dict = Depends(get_current_user)) -> dict:
        user_role = user.get("role", "")
        if len(roles) == 1:
            # Single arg: treat as minimum role in hierarchy
            if ROLE_HIERARCHY.get(user_role, -1) < ROLE_HIERARCHY.get(roles[0], 999):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        else:
            # Multiple args: explicit allowlist
            if user_role not in roles:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user
    return dependency
