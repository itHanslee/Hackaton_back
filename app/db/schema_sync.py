"""Sincroniza columnas faltantes en BD existente (create_all no altera tablas)."""

import logging

from sqlalchemy import inspect, text

from app.db.database import Base, engine
from app.db.indexes import ensure_indexes

logger = logging.getLogger(__name__)

# (column_name, postgresql_type, sqlite_type)
_COLUMN_PATCHES: dict[str, list[tuple[str, str, str]]] = {
    "medicamentos_eps": [
        ("nombre_generico", "VARCHAR", "TEXT"),
        ("nombre_comercial", "VARCHAR", "TEXT"),
        ("categoria", "VARCHAR", "TEXT"),
        ("diagnosticos_aplica", "JSONB", "JSON"),
        ("disponible", "BOOLEAN DEFAULT TRUE", "BOOLEAN DEFAULT 1"),
    ],
    "consultas": [
        ("created_at", "TIMESTAMP", "DATETIME"),
    ],
    "historiales": [
        ("medicamentos_sugeridos", "JSONB", "JSON"),
        ("confirmado_por_medico", "BOOLEAN DEFAULT FALSE", "BOOLEAN DEFAULT 0"),
        ("pdf_path", "VARCHAR", "TEXT"),
        ("created_at", "TIMESTAMP", "DATETIME"),
    ],
    "citas": [
        ("motivo", "VARCHAR", "TEXT"),
        ("estado", "VARCHAR DEFAULT 'pendiente'", "TEXT DEFAULT 'pendiente'"),
    ],
    "pacientes": [
        ("genero", "VARCHAR", "TEXT"),
        ("telefono", "VARCHAR", "TEXT"),
        ("email", "VARCHAR", "TEXT"),
        ("password_hash", "VARCHAR", "TEXT"),
    ],
    "medicos": [
        ("eps_id", "INTEGER", "INTEGER"),
        ("email", "VARCHAR", "TEXT"),
        ("password_hash", "VARCHAR", "TEXT"),
        ("firma_path", "VARCHAR", "TEXT"),
        ("firma_imagen", "BYTEA", "BLOB"),
    ],
    "eps": [
        ("logo_path", "VARCHAR", "TEXT"),
    ],
}


def sync_schema() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_indexes()

    dialect = engine.dialect.name
    if dialect not in {"postgresql", "sqlite"}:
        return

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table, columns in _COLUMN_PATCHES.items():
            if table not in existing_tables:
                continue
            existing_cols = {c["name"] for c in inspector.get_columns(table)}
            for col_name, pg_type, sqlite_type in columns:
                if col_name in existing_cols:
                    continue
                col_type = pg_type if dialect == "postgresql" else sqlite_type
                if dialect == "postgresql":
                    stmt = text(
                        f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS "{col_name}" {col_type}'
                    )
                else:
                    stmt = text(f'ALTER TABLE "{table}" ADD COLUMN "{col_name}" {col_type}')
                try:
                    conn.execute(stmt)
                    logger.info("Schema sync: added %s.%s", table, col_name)
                    existing_cols.add(col_name)
                except Exception:
                    logger.exception("Schema sync failed for %s.%s", table, col_name)
