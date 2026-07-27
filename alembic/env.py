"""Alembic migration environment — wired to the app's engine and models so
`alembic` commands use the same DATABASE_URL (from config.settings) and metadata
as the running app."""

from logging.config import fileConfig

import backend.db.models  # noqa: F401 — registers models on Base.metadata
from alembic import context
from backend.config import settings
from backend.db.base import Base
from backend.db.engine import engine

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
