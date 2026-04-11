"""
Email dispatcher tests — FR-NOTIF-012.

Covers:
  - dispatch_email skips when user has no email
  - dispatch_email skips when SMTP_HOST not configured
  - _build_email_html escapes XSS in title/body
  - _build_email_html sets dir="rtl" for Arabic
  - _build_email_html sets dir="ltr" for English
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


# ═══════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════


def _make_user(**overrides):
    defaults = {
        "id": "user-001",
        "email": None,
        "preferred_language": "ar",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_notification(**overrides):
    defaults = {
        "title_ar": "عنوان الإشعار",
        "title_en": "Notification Title",
        "body_ar": "نص الإشعار",
        "body_en": "Notification body text",
        "event_type": "payment_received",
        "entity_id": "ent-001",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ═══════════════════════════════════════════════════════════════════
#  dispatch_email tests
# ═══════════════════════════════════════════════════════════════════


class TestDispatchEmail:
    @pytest.mark.asyncio
    async def test_dispatch_email_no_email(self):
        """User without email address → status 'skipped'."""
        from app.services.notification.dispatchers import dispatch_email

        user = _make_user(email=None)
        notif = _make_notification()

        result = await dispatch_email(user, notif)
        assert result["status"] == "skipped"
        assert result["reason"] == "no_email"

    @pytest.mark.asyncio
    async def test_dispatch_email_no_config(self):
        """No SMTP_HOST and no SendGrid → status 'skipped'."""
        from app.services.notification.dispatchers import dispatch_email

        user = _make_user(email="test@example.com")
        notif = _make_notification()

        mock_settings = SimpleNamespace(
            SMTP_HOST="",
            SENDGRID_API_KEY="",
            EMAIL_PROVIDER="smtp",
            SMTP_FROM_NAME="MZADAK",
            SMTP_FROM_EMAIL="noreply@mzadak.com",
        )

        with patch("app.core.config.settings", mock_settings):
            result = await dispatch_email(user, notif)

        assert result["status"] == "skipped"
        assert result["reason"] == "email_not_configured"

    @pytest.mark.asyncio
    async def test_dispatch_email_missing_content(self):
        """Notification with empty title/body → status 'skipped'."""
        from app.services.notification.dispatchers import dispatch_email

        user = _make_user(email="test@example.com")
        notif = _make_notification(title_ar="", body_ar="")

        result = await dispatch_email(user, notif)
        assert result["status"] == "skipped"
        assert result["reason"] == "missing_content"


# ═══════════════════════════════════════════════════════════════════
#  _build_email_html tests
# ═══════════════════════════════════════════════════════════════════


class TestBuildEmailHtml:
    def test_escapes_xss_in_title(self):
        """Title with <script> tag gets HTML-escaped."""
        from app.services.notification.dispatchers import _build_email_html

        html = _build_email_html(
            title='<script>alert("xss")</script>',
            body="Safe body text",
            lang="en",
        )
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert "alert" in html  # Content preserved, just escaped

    def test_escapes_xss_in_body(self):
        """Body with <img onerror> gets HTML-escaped."""
        from app.services.notification.dispatchers import _build_email_html

        html = _build_email_html(
            title="Safe Title",
            body='<img onerror="alert(1)" src=x>',
            lang="en",
        )
        assert "<img" not in html
        assert "&lt;img" in html

    def test_rtl_direction_for_arabic(self):
        """Arabic language → dir='rtl'."""
        from app.services.notification.dispatchers import _build_email_html

        html = _build_email_html(
            title="عنوان",
            body="نص",
            lang="ar",
        )
        assert 'dir="rtl"' in html
        assert 'lang="ar"' in html

    def test_ltr_direction_for_english(self):
        """English language → dir='ltr'."""
        from app.services.notification.dispatchers import _build_email_html

        html = _build_email_html(
            title="Title",
            body="Body",
            lang="en",
        )
        assert 'dir="ltr"' in html
        assert 'lang="en"' in html

    def test_contains_mzadak_branding(self):
        """Email HTML includes MZADAK header branding."""
        from app.services.notification.dispatchers import _build_email_html

        html = _build_email_html(
            title="Test",
            body="Test body",
            lang="en",
        )
        assert "MZADAK" in html
        assert "مزادك" in html

    def test_html_structure(self):
        """Output is valid HTML with doctype."""
        from app.services.notification.dispatchers import _build_email_html

        html = _build_email_html(
            title="Test",
            body="Body",
            lang="en",
        )
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html
        assert "</body>" in html
