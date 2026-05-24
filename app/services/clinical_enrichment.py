"""Enriquecimiento de historiales clínicos con contexto previo y medicamentos EPS."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.db_models import Paciente
from app.services.clinical_context import (
    apply_prior_clinical_safety,
    load_patient_clinical_context,
)
from app.services.medicamentos import MedicamentosService


def enrich_historial_for_patient(
    db: Session,
    paciente_id: int,
    historial_dict: dict[str, Any],
) -> dict[str, Any]:
    """Aplica seguridad clínica previa y enriquece medicamentos según EPS del paciente."""
    _, prior_rows = load_patient_clinical_context(db, paciente_id)
    allergy_terms = apply_prior_clinical_safety(historial_dict, prior_rows)
    paciente = db.query(Paciente).filter(Paciente.id == paciente_id).first()
    if paciente and paciente.eps_id:
        historial_dict = MedicamentosService().enrich_historial(
            db, paciente.eps_id, historial_dict, allergy_terms=allergy_terms
        )
    return historial_dict
