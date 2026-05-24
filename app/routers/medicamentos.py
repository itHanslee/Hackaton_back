from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.responses import error_response, ok
from app.db.database import get_db
from app.services.medicamentos import MedicamentosService

router = APIRouter(prefix="/medicamentos", tags=["medicamentos"])


@router.get("")
def get_medicamentos(
    diagnostico: str | None = None,
    eps_id: int | None = None,
    db: Session = Depends(get_db),
):
    if not diagnostico or eps_id is None:
        return error_response(
            "VALIDATION_ERROR",
            "Los parámetros 'diagnostico' y 'eps_id' son requeridos.",
            400,
        )

    result = MedicamentosService().get_by_diagnostico(db, eps_id, diagnostico)
    return ok(result)
