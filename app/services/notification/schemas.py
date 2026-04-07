"""Notification schemas."""

from pydantic import BaseModel


class NotificationOut(BaseModel):
    id: str
    user_id: str
    channel: str
    title_ar: str
    title_en: str
    body_ar: str
    body_en: str
    is_read: bool
    sent_at: str | None = None

    model_config = {"from_attributes": True}


class NotificationListResponse(BaseModel):
    data: list[NotificationOut]
    unread_count: int


class MarkReadRequest(BaseModel):
    notification_ids: list[str]


class PreferenceOut(BaseModel):
    push_enabled: bool
    sms_enabled: bool
    email_enabled: bool
    whatsapp_enabled: bool

    model_config = {"from_attributes": True}


class PreferenceUpdateRequest(BaseModel):
    push_enabled: bool | None = None
    sms_enabled: bool | None = None
    email_enabled: bool | None = None
    whatsapp_enabled: bool | None = None
