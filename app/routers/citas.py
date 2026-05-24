from datetime import datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import get_auth_claims
from app.core.responses import error_response, ok
from app.db.database import get_db
from app.models.db_models import Cita, Medico, Paciente
from app.models.schemas import CitaCreate, CitaResponse
from app.services.slots import SlotsService

router = APIRouter(prefix="/citas", tags=["citas"])


def _parse_fecha_hora(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    return parsed.replace(microsecond=0)


@router.post("")
def create_cita(
    cita: CitaCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    claims = get_auth_claims(request)
    paciente_id = cita.paciente_id

    if claims and claims.get("role") == "paciente":
        own_id = claims.get("subject_id")
        if paciente_id != own_id:
            return error_response(
                "FORBIDDEN",
                "Como paciente solo puede agendar citas para su cuenta.",
                403,
            )

    paciente = db.query(Paciente).filter(Paciente.id == paciente_id).first()
    if not paciente:
        return error_response(
            "NOT_FOUND",
            f"Paciente con id={paciente_id} no existe. Inicie sesión como paciente o use un ID válido.",
            404,
        )

    medico = db.query(Medico).filter(Medico.id == cita.medico_id).first()
    if not medico:
        return error_response(
            "NOT_FOUND",
            f"Médico con id={cita.medico_id} no existe.",
            404,
        )

    fecha_hora = _parse_fecha_hora(cita.fecha_hora)
    if fecha_hora is None:
        return error_response(
            "INVALID_DATETIME",
            "Formato de fecha_hora inválido. Use ISO 8601.",
            400,
        )

    slots_service = SlotsService(db)
    if not slots_service.is_slot_available(cita.medico_id, fecha_hora):
        return error_response(
            "SLOT_UNAVAILABLE",
            "El horario seleccionado no está disponible.",
            409,
        )

    db_cita = Cita(
        paciente_id=paciente_id,
        medico_id=cita.medico_id,
        fecha_hora=fecha_hora,
        motivo=cita.motivo,
        estado="pendiente",
    )
    db.add(db_cita)
    db.commit()
    db.refresh(db_cita)
    return ok(
        CitaResponse(
            id=db_cita.id,
            paciente_id=db_cita.paciente_id,
            medico_id=db_cita.medico_id,
            fecha_hora=db_cita.fecha_hora.isoformat(),
            motivo=db_cita.motivo,
            estado=db_cita.estado,
        ).model_dump()
    )
