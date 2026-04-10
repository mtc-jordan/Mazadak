"""
Structured JSON logging via structlog — SDD §6.1.

Call ``setup_logging()`` once at app startup (inside create_app).
All subsequent ``structlog.get_logger()`` calls return a bound logger
that emits JSON lines with timestamp, level, logger name, and event.
"""

from __future__ import annotations

import logging
import sys

import structlog

from app.core.config import settings


def setup_logging() -> None:
    """Configure structlog + stdlib logging for JSON output."""

    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    # Shared processors used by both structlog and stdlib integration
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if settings.DEBUG:
        # Pretty console output for local development
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer()
    else:
        # JSON lines for production (ELK / CloudWatch / Loki)
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    # Silence noisy third-party loggers
    for name in ("uvicorn.access", "sqlalchemy.engine", "celery"):
        logging.getLogger(name).setLevel(logging.WARNING)
