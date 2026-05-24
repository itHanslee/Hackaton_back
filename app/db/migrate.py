"""Aplicación de migraciones Alembic en runtime."""

from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.core.config import get_settings
from app.db.database import engine
from app.db.indexes import ensure_indexes

logger = logging.getLogger(__name__)
_ROOT = Path(__file__).resolve().parents[2]


def alembic_config() -> Config:
    cfg = Config(str(_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    return cfg


def upgrade_head() -> None:
    cfg = alembic_config()
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    has_app_tables = bool(existing_tables - {"alembic_version"})
    has_version_table = "alembic_version" in existing_tables

    if has_app_tables and not has_version_table:
        logger.info("BD existente sin alembic_version — aplicando stamp head")
        command.stamp(cfg, "head")
        ensure_indexes()
        return

    logger.info("Alembic: upgrade head")
    command.upgrade(cfg, "head")
    ensure_indexes()
    logger.info("Alembic: migraciones aplicadas")
