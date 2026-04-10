"""
Audio transcription via OpenAI Whisper — FR-BOT-003.

Downloads the audio file from Meta Cloud API, then transcribes
using the Whisper medium model (good balance for Jordanian Arabic).
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


async def download_whatsapp_media(media_id: str) -> bytes | None:
    """Download a media file from Meta Cloud API.

    Two-step process:
      1. GET /{media_id} to obtain the download URL
      2. GET the download URL to fetch the actual file bytes
    """
    headers = {"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}"}

    async with httpx.AsyncClient(timeout=30) as client:
        # Step 1: get download URL
        meta_url = f"https://graph.facebook.com/v19.0/{media_id}"
        resp = await client.get(meta_url, headers=headers)
        if resp.status_code != 200:
            logger.error("Failed to get media URL for %s: %d", media_id, resp.status_code)
            return None

        download_url = resp.json().get("url")
        if not download_url:
            logger.error("No URL in media response for %s", media_id)
            return None

        # Step 2: download the actual audio file
        resp = await client.get(download_url, headers=headers)
        if resp.status_code != 200:
            logger.error("Failed to download media %s: %d", media_id, resp.status_code)
            return None

        return resp.content


async def transcribe_audio(audio_bytes: bytes) -> str | None:
    """Transcribe audio bytes using OpenAI Whisper API.

    Uses the Whisper medium model with Arabic language hint for
    optimal Jordanian dialect recognition.

    Returns the transcribed text, or None on failure.
    """
    if not settings.OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY not set — skipping transcription")
        return None

    # Write to temp file (Whisper API requires a file upload)
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
        f.write(audio_bytes)
        tmp_path = Path(f.name)

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                data={
                    "model": "whisper-1",
                    "language": "ar",
                    "prompt": "مزاد مزايدة دينار أردني سعر",  # domain hint
                },
                files={"file": ("audio.ogg", tmp_path.read_bytes(), "audio/ogg")},
            )

        if resp.status_code != 200:
            logger.error("Whisper API error %d: %s", resp.status_code, resp.text[:200])
            return None

        text = resp.json().get("text", "").strip()
        logger.info("Transcribed audio: %s", text[:100])
        return text if text else None

    except Exception as exc:
        logger.error("Whisper transcription failed: %s", exc)
        return None
    finally:
        tmp_path.unlink(missing_ok=True)
