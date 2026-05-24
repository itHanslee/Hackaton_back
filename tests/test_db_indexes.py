from sqlalchemy import inspect, text

from app.db.database import engine
from app.db.schema_sync import sync_schema

_EXPECTED_INDEXES: dict[str, set[str]] = {
    "citas": {
        "idx_citas_paciente_id",
        "idx_citas_medico_id",
        "idx_citas_fecha_hora",
    },
    "consultas": {"idx_consultas_cita_id"},
    "historiales": {
        "idx_historiales_consulta_id",
        "idx_historiales_created_at_desc",
    },
}


def _index_names(table: str) -> set[str]:
    return {idx["name"] for idx in inspect(engine).get_indexes(table)}


def _index_definition(name: str) -> str | None:
    if engine.dialect.name == "sqlite":
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT sql FROM sqlite_master "
                    "WHERE type = 'index' AND name = :name"
                ),
                {"name": name},
            ).fetchone()
        return row[0] if row else None

    if engine.dialect.name == "postgresql":
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT indexdef FROM pg_indexes WHERE indexname = :name"),
                {"name": name},
            ).fetchone()
        return row[0] if row else None

    return None


def _assert_expected_indexes() -> None:
    for table, names in _EXPECTED_INDEXES.items():
        present = _index_names(table)
        missing = names - present
        assert not missing, f"Missing indexes on {table}: {sorted(missing)}"

    desc_def = _index_definition("idx_historiales_created_at_desc")
    assert desc_def is not None
    assert "DESC" in desc_def.upper()


def test_sync_schema_creates_indexes():
    sync_schema()
    _assert_expected_indexes()


def test_sync_schema_indexes_idempotent():
    sync_schema()
    sync_schema()
    _assert_expected_indexes()
