from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.db_models import Cita, EPS, Historial, Medico, Paciente

router = APIRouter(prefix="/citas", tags=["citas"])


def _calendar_item(db: Session, cita: Cita) -> dict[str, Any]:
    paciente = db.query(Paciente).filter(Paciente.id == cita.paciente_id).first()
    medico = db.query(Medico).filter(Medico.id == cita.medico_id).first()
    eps = db.query(EPS).filter(EPS.id == paciente.eps_id).first() if paciente else None
    historial = db.query(Historial).filter(Historial.consulta_id == cita.id).first()
    return {
        "id": f"cita-{cita.id}",
        "paciente_id": f"pac-{paciente.id}" if paciente else "",
        "paciente_nombre": paciente.nombre if paciente else "Paciente",
        "paciente_documento": paciente.cedula if paciente else "",
        "paciente_eps": eps.nombre if eps else "",
        "medico_id": medico.id if medico else cita.medico_id,
        "medico_nombre": medico.nombre if medico else "Medico",
        "especialidad": medico.especialidad if medico else "General",
        "fecha_hora": cita.fecha_hora.isoformat() if cita.fecha_hora else datetime.utcnow().isoformat(),
        "estado": cita.estado,
        "motivo": cita.motivo,
        "historial_id": historial.id if historial else cita.id,
    }


@router.post("")
def create_cita(payload: dict[str, Any], db: Session = Depends(get_db)):
    paciente_id = int(str(payload.get("paciente_id", "0")).replace("pac-", ""))
    medico_id = int(payload.get("medico_id") or 1)
    slot_id = int(payload.get("slot_id") or medico_id * 100 + 1)

    paciente = db.query(Paciente).filter(Paciente.id == paciente_id).first()
    medico = db.query(Medico).filter(Medico.id == medico_id).first()
    if not paciente:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")
    if not medico:
        raise HTTPException(status_code=404, detail="Medico no encontrado")

    slot_index = max(0, (slot_id % 100) - 1)
    fecha_hora = datetime.utcnow().replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(hours=slot_index)
    cita = Cita(
        paciente_id=paciente.id,
        medico_id=medico.id,
        fecha_hora=fecha_hora,
        motivo=str(payload.get("motivo") or "Consulta general"),
        estado="programada",
    )
    db.add(cita)
    db.commit()
    db.refresh(cita)
    return {
        "data": {
            "id": cita.id,
            "paciente_id": paciente.id,
            "medico_id": medico.id,
            "slot_id": slot_id,
            "historial_id": cita.id,
            "estado": cita.estado,
        },
        "error": None,
    }


@router.get("/calendario")
def list_calendario(medico_id: int | None = None, db: Session = Depends(get_db)):
    query = db.query(Cita).order_by(Cita.fecha_hora.asc())
    if medico_id:
        query = query.filter(Cita.medico_id == medico_id)
    return {"data": [_calendar_item(db, cita) for cita in query.all()], "error": None}


@router.get("/{id}")
def get_cita(id: str, db: Session = Depends(get_db)):
    raw_id = int(id.replace("cita-", ""))
    cita = db.query(Cita).filter(Cita.id == raw_id).first()
    if not cita:
        raise HTTPException(status_code=404, detail="Cita no encontrada")
    return {"data": _calendar_item(db, cita), "error": None}
