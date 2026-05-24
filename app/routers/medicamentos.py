from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.responses import error_response, ok
from app.db.database import get_db
from app.models.db_models import EPS, MedicamentoEPS
from app.services.medicamentos import MedicamentosService

router = APIRouter(prefix="/medicamentos", tags=["medicamentos"])


@router.get("/cobertura")
def get_cobertura(
    eps: str,
    nombres: str = "",
    db: Session = Depends(get_db),
):
    eps_row = db.query(EPS).filter(EPS.nombre.ilike(eps.strip())).first()
    if not eps_row:
        return ok([])

    requested = [n.strip() for n in nombres.split(",") if n.strip()]
    if not requested:
        return ok([])

    result = []
    for nombre in requested:
        medicamento = (
            db.query(MedicamentoEPS)
            .filter(
                MedicamentoEPS.eps_id == eps_row.id,
                MedicamentoEPS.nombre.ilike(f"%{nombre}%"),
            )
            .first()
        )
        if medicamento:
            result.append(
                {
                    "nombre": medicamento.nombre,
                    "cubierto": bool(medicamento.disponible),
                    "generico_alternativa": medicamento.nombre_generico
                    or medicamento.descripcion
                    or "Sin alternativa registrada",
                }
            )
        else:
            result.append(
                {
                    "nombre": nombre,
                    "cubierto": False,
                    "generico_alternativa": "No disponible en POS",
                }
            )
    return ok(result)


@router.get("")
def get_medicamentos(
    diagnostico: str | None = None,
    eps_id: int | None = None,
    medico_id: int | None = None,
    db: Session = Depends(get_db),
):
    if medico_id is not None:
        medicamentos = db.query(MedicamentoEPS).limit(50).all()
        return ok(
            [
                {
                    "id": m.id,
                    "nombre": m.nombre,
                    "descripcion": m.descripcion,
                    "eps_id": m.eps_id,
                }
                for m in medicamentos
            ]
        )

    if not diagnostico or eps_id is None:
        return error_response(
            "VALIDATION_ERROR",
            "Los parámetros 'diagnostico' y 'eps_id' son requeridos.",
            400,
        )

    result = MedicamentosService().get_by_diagnostico(db, eps_id, diagnostico)
    return ok(result)
