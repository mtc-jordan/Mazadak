"""
Alembic environment — async PostgreSQL via asyncpg.

Uses the async engine from app.core.database so pool settings,
naming conventions, and the DATABASE_URL all come from one place.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import settings
from app.core.database import Base

# -- Import ALL models so Base.metadata sees every table ---------------
from app.services.auth.models import *        # noqa: F401,F403
from app.services.listing.models import *     # noqa: F401,F403
from app.services.auction.models import *     # noqa: F401,F403
from app.services.escrow.models import *      # noqa: F401,F403
from app.services.notification.models import *  # noqa: F401,F403
from app.services.ai.models import *          # noqa: F401,F403
from app.services.whatsapp_bot.models import *  # noqa: F401,F403

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Override sqlalchemy.url from settings so .env is the single source
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)


def run_migrations_offline() -> None:
    """Emit SQL to stdout (no DB connection needed)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Online mode with async engine — NullPool for short-lived migration."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
