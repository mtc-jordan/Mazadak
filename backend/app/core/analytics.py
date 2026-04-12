"""
ClickHouse analytics pipeline — P1-9.

Event ingestion and query layer for platform analytics.

Tables (created via DDL below):
  - events:        Generic event stream (page views, clicks, searches)
  - auction_events: Auction-specific events (bid, win, cancel, snipe)
  - transaction_events: Financial events (payment, payout, refund)

Events are buffered in-memory and flushed to ClickHouse in batches
via a Celery beat task every 30 seconds. If ClickHouse is down,
events are dropped with a warning (analytics is best-effort).
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core.clickhouse import get_clickhouse_client, query_rows

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
#  DDL — run once to create tables
# ═══════════════════════════════════════════════════════════════════

ANALYTICS_DDL = [
    """
    CREATE TABLE IF NOT EXISTS events (
        event_id     String,
        event_type   LowCardinality(String),
        user_id      String DEFAULT '',
        entity_id    String DEFAULT '',
        entity_type  LowCardinality(String) DEFAULT '',
        properties   String DEFAULT '{}',
        ip_address   String DEFAULT '',
        user_agent   String DEFAULT '',
        created_at   DateTime64(3, 'UTC') DEFAULT now64()
    ) ENGINE = MergeTree()
    ORDER BY (event_type, created_at)
    TTL created_at + INTERVAL 365 DAY
    """,
    """
    CREATE TABLE IF NOT EXISTS auction_events (
        event_id     String,
        auction_id   String,
        event_type   LowCardinality(String),
        user_id      String DEFAULT '',
        bid_amount   Float64 DEFAULT 0,
        currency     LowCardinality(String) DEFAULT 'JOD',
        category_id  UInt32 DEFAULT 0,
        metadata     String DEFAULT '{}',
        created_at   DateTime64(3, 'UTC') DEFAULT now64()
    ) ENGINE = MergeTree()
    ORDER BY (auction_id, created_at)
    TTL created_at + INTERVAL 365 DAY
    """,
    """
    CREATE TABLE IF NOT EXISTS transaction_events (
        event_id      String,
        escrow_id     String,
        event_type    LowCardinality(String),
        buyer_id      String DEFAULT '',
        seller_id     String DEFAULT '',
        amount        Float64 DEFAULT 0,
        platform_fee  Float64 DEFAULT 0,
        currency      LowCardinality(String) DEFAULT 'JOD',
        metadata      String DEFAULT '{}',
        created_at    DateTime64(3, 'UTC') DEFAULT now64()
    ) ENGINE = MergeTree()
    ORDER BY (event_type, created_at)
    TTL created_at + INTERVAL 730 DAY
    """,
]


def ensure_tables() -> bool:
    """Create ClickHouse analytics tables if they don't exist."""
    client = get_clickhouse_client()
    if client is None:
        return False
    try:
        for ddl in ANALYTICS_DDL:
            client.command(ddl.strip())
        logger.info("ClickHouse analytics tables ensured")
        return True
    except Exception:
        logger.exception("Failed to create ClickHouse analytics tables")
        return False


# ═══════════════════════════════════════════════════════════════════
#  Event buffer — batched inserts
# ═══════════════════════════════════════════════════════════════════

_event_buffer: deque[tuple[str, list]] = deque(maxlen=10_000)
_auction_event_buffer: deque[list] = deque(maxlen=10_000)
_transaction_event_buffer: deque[list] = deque(maxlen=5_000)


def track_event(
    event_type: str,
    user_id: str = "",
    entity_id: str = "",
    entity_type: str = "",
    properties: str = "{}",
    ip_address: str = "",
    user_agent: str = "",
) -> None:
    """Buffer a generic analytics event for batch insert."""
    from uuid import uuid4
    now = datetime.now(timezone.utc)
    _event_buffer.append((
        "events",
        [str(uuid4()), event_type, user_id, entity_id, entity_type,
         properties, ip_address, user_agent, now],
    ))


def track_auction_event(
    auction_id: str,
    event_type: str,
    user_id: str = "",
    bid_amount: float = 0,
    currency: str = "JOD",
    category_id: int = 0,
    metadata: str = "{}",
) -> None:
    """Buffer an auction analytics event."""
    from uuid import uuid4
    now = datetime.now(timezone.utc)
    _auction_event_buffer.append(
        [str(uuid4()), auction_id, event_type, user_id, bid_amount,
         currency, category_id, metadata, now],
    )


def track_transaction_event(
    escrow_id: str,
    event_type: str,
    buyer_id: str = "",
    seller_id: str = "",
    amount: float = 0,
    platform_fee: float = 0,
    currency: str = "JOD",
    metadata: str = "{}",
) -> None:
    """Buffer a transaction analytics event."""
    from uuid import uuid4
    now = datetime.now(timezone.utc)
    _transaction_event_buffer.append(
        [str(uuid4()), escrow_id, event_type, buyer_id, seller_id,
         amount, platform_fee, currency, metadata, now],
    )


def flush_events() -> int:
    """Flush all buffered events to ClickHouse. Returns count inserted."""
    client = get_clickhouse_client()
    if client is None:
        # Drop events if ClickHouse is down
        dropped = len(_event_buffer) + len(_auction_event_buffer) + len(_transaction_event_buffer)
        _event_buffer.clear()
        _auction_event_buffer.clear()
        _transaction_event_buffer.clear()
        if dropped:
            logger.warning("Dropped %d analytics events (ClickHouse unavailable)", dropped)
        return 0

    total = 0

    # Generic events
    if _event_buffer:
        rows = [row for _, row in _event_buffer]
        try:
            client.insert(
                "events",
                rows,
                column_names=[
                    "event_id", "event_type", "user_id", "entity_id",
                    "entity_type", "properties", "ip_address", "user_agent",
                    "created_at",
                ],
            )
            total += len(rows)
        except Exception:
            logger.exception("Failed to flush %d generic events", len(rows))
        _event_buffer.clear()

    # Auction events
    if _auction_event_buffer:
        rows = list(_auction_event_buffer)
        try:
            client.insert(
                "auction_events",
                rows,
                column_names=[
                    "event_id", "auction_id", "event_type", "user_id",
                    "bid_amount", "currency", "category_id", "metadata",
                    "created_at",
                ],
            )
            total += len(rows)
        except Exception:
            logger.exception("Failed to flush %d auction events", len(rows))
        _auction_event_buffer.clear()

    # Transaction events
    if _transaction_event_buffer:
        rows = list(_transaction_event_buffer)
        try:
            client.insert(
                "transaction_events",
                rows,
                column_names=[
                    "event_id", "escrow_id", "event_type", "buyer_id",
                    "seller_id", "amount", "platform_fee", "currency",
                    "metadata", "created_at",
                ],
            )
            total += len(rows)
        except Exception:
            logger.exception("Failed to flush %d transaction events", len(rows))
        _transaction_event_buffer.clear()

    if total:
        logger.debug("Flushed %d analytics events to ClickHouse", total)

    return total


# ═══════════════════════════════════════════════════════════════════
#  Query helpers for dashboards
# ═══════════════════════════════════════════════════════════════════

def get_platform_stats(days: int = 30) -> dict[str, Any]:
    """Aggregate platform stats for the last N days."""
    results = {}

    rows = query_rows(
        """
        SELECT
            count() as total_bids,
            uniqExact(user_id) as unique_bidders,
            uniqExact(auction_id) as auctions_with_bids,
            avg(bid_amount) as avg_bid_amount
        FROM auction_events
        WHERE event_type = 'bid_placed'
          AND created_at >= now() - INTERVAL %(days)s DAY
        """,
        {"days": days},
    )
    if rows:
        results["bidding"] = rows[0]

    rows = query_rows(
        """
        SELECT
            event_type,
            count() as cnt,
            sum(amount) as total_amount
        FROM transaction_events
        WHERE created_at >= now() - INTERVAL %(days)s DAY
        GROUP BY event_type
        ORDER BY cnt DESC
        """,
        {"days": days},
    )
    results["transactions"] = rows

    rows = query_rows(
        """
        SELECT
            toDate(created_at) as day,
            count() as events
        FROM events
        WHERE created_at >= now() - INTERVAL %(days)s DAY
        GROUP BY day
        ORDER BY day
        """,
        {"days": days},
    )
    results["daily_activity"] = rows

    return results


def get_category_stats(days: int = 30) -> list[dict]:
    """Bid activity breakdown by category."""
    return query_rows(
        """
        SELECT
            category_id,
            count() as total_bids,
            uniqExact(auction_id) as auctions,
            avg(bid_amount) as avg_bid,
            max(bid_amount) as max_bid
        FROM auction_events
        WHERE event_type = 'bid_placed'
          AND created_at >= now() - INTERVAL %(days)s DAY
        GROUP BY category_id
        ORDER BY total_bids DESC
        """,
        {"days": days},
    )


def get_revenue_stats(days: int = 30) -> list[dict]:
    """Daily revenue breakdown."""
    return query_rows(
        """
        SELECT
            toDate(created_at) as day,
            sum(platform_fee) as revenue,
            sum(amount) as gmv,
            count() as transactions,
            currency
        FROM transaction_events
        WHERE event_type IN ('payment_captured', 'escrow_released')
          AND created_at >= now() - INTERVAL %(days)s DAY
        GROUP BY day, currency
        ORDER BY day
        """,
        {"days": days},
    )
