"""SQLAlchemy declarative base.

All ORM models (added in later milestones, in ``olympus.data.database.models``)
inherit from :class:`Base`. Keeping the base here - free of any concrete model -
means the metadata object is importable without pulling in business entities,
which matters for migrations and for the foundation starting cleanly.

A shared naming convention for constraints/indexes is configured so that
auto-generated migration names are deterministic and stable across machines.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Deterministic naming convention -> stable, reviewable migrations.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base shared by all Olympus ORM models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
