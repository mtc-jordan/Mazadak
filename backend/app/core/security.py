"""
JWT RS256 token issuance & verification, password hashing.

Architecture (from SDD §3.1.1):
- Private key: signs access tokens (kept in keys/ or AWS Secrets Manager)
- Public key: any service can verify tokens without the private key
- Blacklist: Redis SET jti:{token_id} with TTL = remaining validity
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

from app.core.config import settings

# ── Password hashing (bcrypt) ───────────────────────────────────

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ── RSA key loading ─────────────────────────────────────────────

def _load_key(path: str) -> str:
    p = Path(path)
    if p.exists():
        return p.read_text()
    # In production, keys come from AWS Secrets Manager or env vars.
    # For local dev, generate with:
    #   openssl genrsa -out keys/private.pem 2048
    #   openssl rsa -in keys/private.pem -pubout -out keys/public.pem
    return ""


_private_key = _load_key(settings.JWT_PRIVATE_KEY_PATH)
_public_key = _load_key(settings.JWT_PUBLIC_KEY_PATH)

# ── Startup safety checks ──────────────────────────────────────

if settings.ENVIRONMENT == "production":
    if not _private_key or not _public_key:
        raise RuntimeError(
            "JWT RSA keys are missing. Generate them or mount via secrets. "
            "See: openssl genrsa -out keys/private.pem 2048"
        )
    if settings.SECRET_KEY == "change-me-in-production":
        raise RuntimeError(
            "SECRET_KEY is still the default value. Set a secure random key "
            "in production via the SECRET_KEY environment variable."
        )


# ── Token models ────────────────────────────────────────────────

class TokenPayload(BaseModel):
    sub: str                       # user_id (UUID as string)
    role: str                      # user_role enum value
    kyc: str                       # kyc_status enum value
    ats: int                       # ATS score
    jti: str                       # unique token id (for blacklist)
    exp: datetime
    iat: datetime


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


# ── Token creation ──────────────────────────────────────────────

def create_access_token(
    user_id: str,
    role: str,
    kyc_status: str,
    ats_score: int,
) -> tuple[str, str]:
    """Return (encoded_jwt, jti)."""
    now = datetime.now(timezone.utc)
    jti = uuid4().hex
    payload = {
        "sub": user_id,
        "role": role,
        "kyc": kyc_status,
        "ats": ats_score,
        "jti": jti,
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    token = jwt.encode(payload, _private_key, algorithm=settings.JWT_ALGORITHM)
    return token, jti


def create_refresh_token() -> str:
    """Return an opaque 256-bit random token (hex-encoded)."""
    return uuid4().hex + uuid4().hex


# ── Token verification ──────────────────────────────────────────

def decode_access_token(token: str) -> TokenPayload | None:
    """Verify RS256 signature and decode claims. Returns None on failure."""
    try:
        payload = jwt.decode(
            token,
            _public_key,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return TokenPayload(**payload)
    except JWTError:
        return None
