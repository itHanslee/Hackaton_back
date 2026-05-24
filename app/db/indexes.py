"""Índices para optimizar consultas clínicas frecuentes."""

import logging

from sqlalchemy import text

from app.db.database import engine

logger = logging.getLogger(__name__)

_INDEXES: list[tuple[str, str]] = [
    (
        "idx_citas_paciente_id",
        "CREATE INDEX IF NOT EXISTS idx_citas_paciente_id ON citas (paciente_id)",
    ),
    (
        "idx_citas_medico_id",
        "CREATE INDEX IF NOT EXISTS idx_citas_medico_id ON citas (medico_id)",
    ),
    (
        "idx_citas_fecha_hora",
        "CREATE INDEX IF NOT EXISTS idx_citas_fecha_hora ON citas (fecha_hora)",
    ),
    (
        "idx_consultas_cita_id",
        "CREATE INDEX IF NOT EXISTS idx_consultas_cita_id ON consultas (cita_id)",
    ),
    (
        "idx_historiales_consulta_id",
        "CREATE INDEX IF NOT EXISTS idx_historiales_consulta_id ON historiales (consulta_id)",
    ),
    (
        "idx_historiales_created_at_desc",
        "CREATE INDEX IF NOT EXISTS idx_historiales_created_at_desc ON historiales (created_at DESC)",
    ),
]


def ensure_indexes() -> None:
    with engine.begin() as conn:
        for name, stmt in _INDEXES:
            conn.execute(text(stmt))
            logger.info("Ensured index %s", name)
