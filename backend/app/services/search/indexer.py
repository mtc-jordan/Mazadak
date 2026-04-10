"""Startup helper — ensures Meilisearch indexes exist and are configured."""

from __future__ import annotations

import asyncio

from app.services.search.service import configure_meilisearch


async def ensure_indexes() -> None:
    """Run the synchronous configure_meilisearch in a thread to avoid blocking."""
    await asyncio.to_thread(configure_meilisearch)
