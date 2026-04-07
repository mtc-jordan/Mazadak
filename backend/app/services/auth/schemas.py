"""Auth request/response schemas — SDD §5.2."""

from __future__ import annotations

from typing import Annotated

import phonenumbers
from pydantic import BaseModel, Field, field_validator

# Allowed country codes — SDD §5.2, FRD acceptance criterion
ALLOWED_COUNTRY_CODES = {"JO", "SA", "AE"}  # +962, +966, +971


def validate_phone_e164(value: str) -> str:
    """Parse and validate phone number to E.164 format.

    Accepts: +962790000000, +966501234567, +971501234567
    Rejects: non-E.164, wrong country, invalid number.
    """
    try:
        parsed = phonenumbers.parse(value, None)
    except phonenumbers.NumberParseException as exc:
        raise ValueError(f"Invalid phone number format: {exc}") from exc

    if not phonenumbers.is_valid_number(parsed):
        raise ValueError("Phone number is not valid")

    region = phonenumbers.region_code_for_number(parsed)
    if region not in ALLOWED_COUNTRY_CODES:
        raise ValueError(
            f"Phone number must be from Jordan (+962), Saudi Arabia (+966), "
            f"or UAE (+971). Got: {region}"
        )

    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


# Type alias for reuse
Phone = Annotated[str, Field(examples=["+962790000000"])]


# ── Registration / OTP ──────────────────────────────────────────

class RegisterRequest(BaseModel):
    phone: Phone

    @field_validator("phone")
    @classmethod
    def _validate_phone(cls, v: str) -> str:
        return validate_phone_e164(v)


class OTPSentResponse(BaseModel):
    otp_sent: bool = True
    message_en: str = "OTP sent to your phone number"
    message_ar: str = "تم إرسال رمز التحقق إلى رقم هاتفك"


class VerifyOTPRequest(BaseModel):
    phone: Phone
    otp: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")

    @field_validator("phone")
    @classmethod
    def _validate_phone(cls, v: str) -> str:
        return validate_phone_e164(v)


# ── Login ───────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    phone: Phone

    @field_validator("phone")
    @classmethod
    def _validate_phone(cls, v: str) -> str:
        return validate_phone_e164(v)


# ── Token responses ─────────────────────────────────────────────

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class LogoutResponse(BaseModel):
    success: bool = True


# ── User profile ────────────────────────────────────────────────

class UserOut(BaseModel):
    id: str
    phone: str
    full_name_ar: str
    full_name_en: str | None = None
    email: str | None = None
    role: str
    kyc_status: str
    ats_score: int
    ats_tier: str
    country_code: str
    preferred_language: str

    model_config = {"from_attributes": True}


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut


# ── Error detail ────────────────────────────────────────────────

class ErrorDetail(BaseModel):
    code: str
    message_en: str
    message_ar: str = ""
    attempts_remaining: int | None = None
    retry_after_seconds: int | None = None


# ── KYC (FR-AUTH-005) ───────────────────────────────────────────

class KYCInitiateResponse(BaseModel):
    upload_urls: dict[str, str]  # {id_front, id_back, selfie} → presigned PUT URLs
    s3_keys: dict[str, str]      # {id_front, id_back, selfie} → S3 keys to send back in submit
    expires_in: int = 300


class KYCSubmitRequest(BaseModel):
    id_front_key: str = Field(..., min_length=10)
    id_back_key: str = Field(..., min_length=10)
    selfie_key: str = Field(..., min_length=10)


class KYCSubmitResponse(BaseModel):
    status: str  # verified | pending_review | rejected
    message_en: str
    message_ar: str
    confidence: float | None = None


# ── Admin KYC review ────────────────────────────────────────────

class KYCQueueItem(BaseModel):
    id: str
    user_id: str
    user_phone: str
    document_type: str
    s3_key: str
    rekognition_confidence: float | None
    status: str
    created_at: str

    model_config = {"from_attributes": True}


class KYCReviewRequest(BaseModel):
    decision: str = Field(..., pattern=r"^(approve|reject)$")
    reason: str = Field(default="", max_length=500)
