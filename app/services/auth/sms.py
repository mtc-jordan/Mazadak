"""
SMS gateway — Twilio primary, AWS SNS fallback.

SDD §3.1: OTP sent via SMS (Twilio primary, AWS SNS fallback).
FR-AUTH-001: OTP delivery within 30 seconds.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from app.core.config import settings

logger = logging.getLogger(__name__)


class SMSBackend(ABC):
    @abstractmethod
    async def send(self, phone: str, message: str) -> bool: ...


class TwilioBackend(SMSBackend):
    async def send(self, phone: str, message: str) -> bool:
        try:
            from twilio.rest import Client

            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
            client.messages.create(
                body=message,
                from_=settings.TWILIO_PHONE_NUMBER,
                to=phone,
            )
            return True
        except Exception:
            logger.exception("Twilio SMS failed for %s", phone)
            return False


class SNSBackend(SMSBackend):
    async def send(self, phone: str, message: str) -> bool:
        try:
            import boto3

            client = boto3.client(
                "sns",
                region_name=settings.AWS_SNS_REGION,
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            )
            client.publish(
                PhoneNumber=phone,
                Message=message,
                MessageAttributes={
                    "AWS.SNS.SMS.SMSType": {
                        "DataType": "String",
                        "StringValue": "Transactional",
                    }
                },
            )
            return True
        except Exception:
            logger.exception("AWS SNS SMS failed for %s", phone)
            return False


class MockBackend(SMSBackend):
    """For local dev and testing — logs OTP to console."""

    last_otp: str | None = None
    last_phone: str | None = None

    async def send(self, phone: str, message: str) -> bool:
        MockBackend.last_otp = message.split(": ")[-1].strip() if ": " in message else message
        MockBackend.last_phone = phone
        logger.info("MOCK SMS to %s: %s", phone, message)
        return True


async def send_sms(phone: str, message: str) -> bool:
    """Send SMS with automatic fallback: Twilio → SNS."""
    if settings.SMS_PROVIDER == "mock":
        return await MockBackend().send(phone, message)

    # Primary: Twilio
    if await TwilioBackend().send(phone, message):
        return True

    # Fallback: AWS SNS
    logger.warning("Twilio failed, falling back to AWS SNS for %s", phone)
    return await SNSBackend().send(phone, message)
