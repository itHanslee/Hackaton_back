from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import get_auth_claims
from app.core.responses import error_response, ok
from app.db.database import get_db
from app.models.db_models import Cita, Historial, Paciente
from app.models.schemas import CitaResponse, HistorialResponse
from app.services.clinical_context import fetch_prior_historiales

router = APIRouter(prefix="/pacientes", tags=["pacientes"])


def _serialize_historial(historial: Historial) -> dict:
    created_at = historial.created_at.isoformat() if historial.created_at else None
    return HistorialResponse(
        id=historial.id,
        consulta_id=historial.consulta_id,
        motivo_consulta=historial.motivo_consulta,
        sintomas=historial.sintomas,
        diagnostico=historial.diagnostico,
        plan_tratamiento=historial.plan_tratamiento,
        medicamentos_sugeridos=historial.medicamentos_sugeridos,
        confirmado_por_medico=historial.confirmado_por_medico,
        pdf_path=historial.pdf_path,
        created_at=created_at,
    ).model_dump()


def _serialize_cita(cita: Cita) -> dict:
    return CitaResponse(
        id=cita.id,
        paciente_id=cita.paciente_id,
        medico_id=cita.medico_id,
        fecha_hora=cita.fecha_hora.isoformat() if cita.fecha_hora else "",
        motivo=cita.motivo,
        estado=cita.estado,
    ).model_dump()


def _historiales_for_paciente(db: Session, paciente_id: int) -> list[Historial]:
    return fetch_prior_historiales(db, paciente_id)


@router.get("/me/historial")
def get_my_historial(request: Request, db: Session = Depends(get_db)):
    claims = get_auth_claims(request)
    if not claims or claims.get("role") != "paciente":
        return error_response("FORBIDDEN", "Solo pacientes autenticados.", 403)

    paciente_id = claims["subject_id"]
    historiales = _historiales_for_paciente(db, paciente_id)
    return ok([_serialize_historial(h) for h in historiales])


@router.get("/me/citas")
def get_my_citas(request: Request, db: Session = Depends(get_db)):
    claims = get_auth_claims(request)
    if not claims or claims.get("role") != "paciente":
        return error_response("FORBIDDEN", "Solo pacientes autenticados.", 403)

    paciente_id = claims["subject_id"]
    citas = (
        db.query(Cita)
        .filter(Cita.paciente_id == paciente_id)
        .order_by(Cita.fecha_hora.desc())
        .all()
    )
    return ok([_serialize_cita(c) for c in citas])


@router.get("/{id}/historial")
def get_paciente_historial(id: int, db: Session = Depends(get_db)):
    paciente = db.query(Paciente).filter(Paciente.id == id).first()
    if not paciente:
        return error_response("NOT_FOUND", "Paciente no encontrado", 404)

    historiales = _historiales_for_paciente(db, id)
    return ok([_serialize_historial(h) for h in historiales])
