"""TenantMiddleware — resolves tenant from JWT and attaches to request.state."""

from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from jose import JWTError

from core.auth.jwt_utils import decode_access_token

# Paths that don't require tenant resolution
_PUBLIC_PREFIXES = ("/auth/", "/docs", "/openapi", "/redoc", "/health",
                    "/api/health", "/api/discovery", "/api/stm")


class TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip public routes
        path = request.url.path
        if any(path.startswith(p) for p in _PUBLIC_PREFIXES):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return await call_next(request)

        token = auth_header.removeprefix("Bearer ").strip()
        try:
            payload = decode_access_token(token)
            request.state.tenant_id = payload.get("tenant_id")
            request.state.user_sub = payload.get("sub")
            request.state.user_role = payload.get("role")
        except JWTError:
            pass  # let route-level auth handle rejection

        return await call_next(request)


def get_tenant_id(request: Request) -> str:
    """FastAPI dependency — extracts tenant_id from request.state."""
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tenant context not found",
        )
    return tenant_id
