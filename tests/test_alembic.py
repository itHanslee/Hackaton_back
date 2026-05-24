"""Tests de migraciones Alembic."""

from pathlib import Path

import pytest
from sqlalchemy import inspect

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def alembic_db(tmp_path, monkeypatch):
    db_path = tmp_path / "alembic_test.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("USE_ALEMBIC", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield url
    get_settings.cache_clear()


def test_upgrade_head_creates_tables(alembic_db):
    from app.core.config import get_settings
    from app.db.database import engine
    from app.db.migrate import upgrade_head

    upgrade_head()

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert "alembic_version" in tables
    for expected in (
        "eps",
        "pacientes",
        "medicos",
        "citas",
        "consultas",
        "historiales",
        "incapacidad_radicacion_jobs",
        "medicamentos_eps",
    ):
        assert expected in tables

    get_settings.cache_clear()


def test_stamp_existing_database_without_alembic_version(tmp_path, monkeypatch):
    """BD creada con create_all debe marcarse en head sin re-ejecutar DDL."""
    db_path = tmp_path / "legacy.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("USE_ALEMBIC", "true")
    from app.core.config import get_settings
    from app.db.database import Base, engine
    from app.models import db_models  # noqa: F401

    get_settings.cache_clear()
    Base.metadata.create_all(bind=engine)

    from app.db.migrate import upgrade_head

    upgrade_head()

    inspector = inspect(engine)
    assert inspector.has_table("alembic_version")
    get_settings.cache_clear()
