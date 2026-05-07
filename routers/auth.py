import uuid
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from core.auth.hashing import hash_password, verify_password
from core.auth.jwt_utils import create_access_token, create_refresh_token, hash_refresh_token
from core.db.platform import get_platform_session_factory
from core.models.platform import Tenant, TenantUser, RefreshToken
from core.tenant.provisioner import provision_tenant_db, encrypt_db_url
from core.config import get_settings

router = APIRouter(tags=["auth"])

class SignupRequest(BaseModel):
    name: str; slug: str; email: str; password: str

class LoginRequest(BaseModel):
    email: str; password: str

class TokenResponse(BaseModel):
    access_token: str; refresh_token: str; token_type: str = "bearer"

@router.post("/signup", response_model=TokenResponse)
async def signup(req: SignupRequest):
    settings = get_settings()
    async with get_platform_session_factory()() as db:
        if (await db.execute(select(TenantUser).where(TenantUser.email == req.email))).scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Email already registered")
        db_url = provision_tenant_db(req.slug, settings.DATABASE_URL)
        tenant = Tenant(id=uuid.uuid4(), name=req.name, slug=req.slug, db_url_encrypted=encrypt_db_url(db_url))
        db.add(tenant)
        user = TenantUser(id=uuid.uuid4(), tenant_id=tenant.id, email=req.email, hashed_password=hash_password(req.password), role="admin")
        db.add(user)
        refresh_raw = create_refresh_token()
        db.add(RefreshToken(id=uuid.uuid4(), user_id=user.id, token_hash=hash_refresh_token(refresh_raw),
                            expires_at=datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)))
        await db.commit()
    return TokenResponse(access_token=create_access_token(str(user.id), str(tenant.id), user.role), refresh_token=refresh_raw)

@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    settings = get_settings()
    async with get_platform_session_factory()() as db:
        user = (await db.execute(select(TenantUser).where(TenantUser.email == req.email))).scalar_one_or_none()
        if not user or not verify_password(req.password, user.hashed_password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        refresh_raw = create_refresh_token()
        db.add(RefreshToken(id=uuid.uuid4(), user_id=user.id, token_hash=hash_refresh_token(refresh_raw),
                            expires_at=datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)))
        await db.commit()
    return TokenResponse(access_token=create_access_token(str(user.id), str(user.tenant_id), user.role), refresh_token=refresh_raw)
