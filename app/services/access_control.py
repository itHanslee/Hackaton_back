"""Controles de acceso médico ↔ paciente."""

from sqlalchemy.orm import Session

from app.models.db_models import Cita


def medico_has_paciente(db: Session, medico_id: int, paciente_id: int) -> bool:
    row = (
        db.query(Cita.id)
        .filter(Cita.medico_id == medico_id, Cita.paciente_id == paciente_id)
        .first()
    )
    return row is not None
