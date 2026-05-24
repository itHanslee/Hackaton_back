"""Sincroniza columnas faltantes en BD existente (create_all no altera tablas)."""

import logging

from sqlalchemy import inspect, text

from app.db.database import Base, engine
from app.db.indexes import ensure_indexes

logger = logging.getLogger(__name__)

_PG_COLUMN_PATCHES: dict[str, list[tuple[str, str]]] = {
    "medicamentos_eps": [
        ("nombre_generico", "VARCHAR"),
        ("nombre_comercial", "VARCHAR"),
        ("categoria", "VARCHAR"),
        ("diagnosticos_aplica", "JSONB"),
        ("disponible", "BOOLEAN DEFAULT TRUE"),
    ],
    "consultas": [
        ("created_at", "TIMESTAMP"),
    ],
    "historiales": [
        ("medicamentos_sugeridos", "JSONB"),
        ("confirmado_por_medico", "BOOLEAN DEFAULT FALSE"),
        ("pdf_path", "VARCHAR"),
        ("created_at", "TIMESTAMP"),
    ],
    "citas": [
        ("motivo", "VARCHAR"),
        ("estado", "VARCHAR DEFAULT 'pendiente'"),
    ],
    "pacientes": [
        ("genero", "VARCHAR"),
        ("telefono", "VARCHAR"),
        ("email", "VARCHAR"),
        ("password_hash", "VARCHAR"),
    ],
    "medicos": [
        ("eps_id", "INTEGER"),
        ("email", "VARCHAR"),
        ("password_hash", "VARCHAR"),
        ("firma_path", "VARCHAR"),
    ],
    "eps": [
        ("logo_path", "VARCHAR"),
    ],
}


def sync_schema() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_indexes()
    if engine.dialect.name != "postgresql":
        return

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table, columns in _PG_COLUMN_PATCHES.items():
            if table not in existing_tables:
                continue
            existing_cols = {c["name"] for c in inspector.get_columns(table)}
            for col_name, col_type in columns:
                if col_name in existing_cols:
                    continue
                stmt = text(
                    f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS "{col_name}" {col_type}'
                )
                conn.execute(stmt)
                logger.info("Schema sync: added %s.%s", table, col_name)
