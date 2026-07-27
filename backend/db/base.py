"""Declarative base for all ORM models. Kept in its own module so Alembic's
env.py and the models can both import `Base` without circular imports."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
