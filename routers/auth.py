"""FastAPI auth router — signup, login, refresh, logout."""

import hashlib
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.hashing import hash_password, verify_password
from core.auth.jwt_utils import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
)
from core.auth.middleware import TokenPayload, get_current_user
from core.db.platform import get_platform_session
from core.models.platform import RefreshToken, Tenant, TenantUser
from core.tenant.provisioner import provision_tenant

router = APIRouter(prefix="/auth", tags=["auth"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class SignupRequest(BaseModel):
    tenant_name: str
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    tenant_slug: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    body: SignupRequest,
    session: AsyncSession = Depends(get_platform_session),
):
    from core.config import get_settings
    settings = get_settings()

    tenant, admin = await provision_tenant(
        session=session,
        name=body.tenant_name,
        admin_email=body.email,
        admin_password=body.password,
        platform_db_url=settings.DATABASE_URL.replace("+asyncpg", ""),
    )

    access_token = create_access_token(
        subject=str(admin.id),
        tenant_id=str(tenant.id),
        role=admin.role,
    )
    refresh_token, expires_at = create_refresh_token(
        subject=str(admin.id),
        tenant_id=str(tenant.id),
    )

    rt = RefreshToken(
        id=uuid.uuid4(),
        user_id=admin.id,
        token_hash=_hash_token(refresh_token),
        expires_at=expires_at,
    )
    session.add(rt)

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    session: AsyncSession = Depends(get_platform_session),
):
    # Resolve tenant
    tenant_row = (
        await session.execute(select(Tenant).where(Tenant.slug == body.tenant_slug))
    ).scalar_one_or_none()
    if not tenant_row or not tenant_row.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    # Resolve user
    user_row = (
        await session.execute(
            select(TenantUser).where(
                TenantUser.tenant_id == tenant_row.id,
                TenantUser.email == body.email,
                TenantUser.is_active == True,
            )
        )
    ).scalar_one_or_none()

    if not user_row or not verify_password(body.password, user_row.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )

    access_token = create_access_token(
        subject=str(user_row.id),
        tenant_id=str(tenant_row.id),
        role=user_row.role,
    )
    refresh_token, expires_at = create_refresh_token(
        subject=str(user_row.id),
        tenant_id=str(tenant_row.id),
    )

    rt = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_row.id,
        token_hash=_hash_token(refresh_token),
        expires_at=expires_at,
    )
    session.add(rt)

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest,
    session: AsyncSession = Depends(get_platform_session),
):
    try:
        payload = decode_refresh_token(body.refresh_token)
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    token_hash = _hash_token(body.refresh_token)
    rt_row = (
        await session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
    ).scalar_one_or_none()

    if not rt_row or rt_row.revoked:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked")

    now = datetime.now(tz=timezone.utc)
    if rt_row.expires_at.replace(tzinfo=timezone.utc) < now:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")

    # Revoke old token
    rt_row.revoked = True
    await session.flush()

    # Fetch user for role
    user_row = await session.get(TenantUser, rt_row.user_id)
    if not user_row or not user_row.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    access_token = create_access_token(
        subject=payload["sub"],
        tenant_id=payload["tenant_id"],
        role=user_row.role,
    )
    new_refresh, new_expires = create_refresh_token(
        subject=payload["sub"],
        tenant_id=payload["tenant_id"],
    )

    new_rt = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_row.id,
        token_hash=_hash_token(new_refresh),
        expires_at=new_expires,
    )
    session.add(new_rt)

    return TokenResponse(access_token=access_token, refresh_token=new_refresh)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: RefreshRequest,
    session: AsyncSession = Depends(get_platform_session),
    _: TokenPayload = Depends(get_current_user),
):
    token_hash = _hash_token(body.refresh_token)
    rt_row = (
        await session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
    ).scalar_one_or_none()
    if rt_row:
        rt_row.revoked = True
