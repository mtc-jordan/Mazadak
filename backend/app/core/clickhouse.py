"""
ClickHouse client — SDD §4.3 analytics database.

Provides a lazy-initialised connection to the ClickHouse analytics
database used for Price Oracle comparables and event tracking.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

_client = None


def get_clickhouse_client():
    """Lazy-initialise and return ClickHouse client."""
    global _client
    if _client is None:
        try:
            import clickhouse_connect
            _client = clickhouse_connect.get_client(
                host=settings.CLICKHOUSE_HOST,
                port=settings.CLICKHOUSE_PORT,
                database=settings.CLICKHOUSE_DATABASE,
            )
        except Exception:
            logger.warning("ClickHouse unavailable — using fallback")
            return None
    return _client


def query_rows(sql: str, parameters: dict | None = None) -> list[dict[str, Any]]:
    """Execute a ClickHouse query and return rows as list of dicts."""
    client = get_clickhouse_client()
    if client is None:
        return []
    try:
        result = client.query(sql, parameters=parameters or {})
        columns = result.column_names
        return [dict(zip(columns, row)) for row in result.result_rows]
    except Exception:
        logger.exception("ClickHouse query failed")
        return []
