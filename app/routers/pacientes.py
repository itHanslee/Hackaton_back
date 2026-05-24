from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.db_models import Cita, EPS, Historial, Medico, Paciente

router = APIRouter(prefix="/pacientes", tags=["pacientes"])


def _eps_name(db: Session, eps_id: int | None) -> str:
    eps = db.query(EPS).filter(EPS.id == eps_id).first() if eps_id else None
    return eps.nombre if eps else ""


def _eps_id(db: Session, eps_name: str | None) -> int:
    name = (eps_name or "Sura").strip() or "Sura"
    eps = db.query(EPS).filter(EPS.nombre == name).first()
    if eps:
        return eps.id
    eps = EPS(nombre=name)
    db.add(eps)
    db.commit()
    db.refresh(eps)
    return eps.id


def _summary(db: Session, paciente: Paciente) -> dict[str, Any]:
    citas = db.query(Cita).filter(Cita.paciente_id == paciente.id).all()
    ultima = max((c.fecha_hora for c in citas if c.fecha_hora), default=None)
    return {
        "id": f"pac-{paciente.id}",
        "nombre": paciente.nombre,
        "documento": paciente.cedula,
        "eps": _eps_name(db, paciente.eps_id),
        "telefono": paciente.telefono,
        "ultima_consulta": ultima.isoformat() if ultima else "",
        "total_consultas": len(citas),
    }


@router.get("")
def list_pacientes(db: Session = Depends(get_db)):
    pacientes = db.query(Paciente).order_by(Paciente.id.desc()).all()
    return {"data": [_summary(db, p) for p in pacientes], "error": None}


@router.post("")
def create_paciente(payload: dict[str, Any], db: Session = Depends(get_db)):
    documento = str(payload.get("documento") or payload.get("cedula") or "").strip()
    if not documento:
        raise HTTPException(status_code=400, detail="Documento requerido")

    existing = db.query(Paciente).filter(Paciente.cedula == documento).first()
    if existing:
        return {
            "data": {
                "id": existing.id,
                "documento": existing.cedula,
                "nombre": existing.nombre,
                "telefono": existing.telefono,
                "eps": _eps_name(db, existing.eps_id),
            },
            "error": None,
        }

    paciente = Paciente(
        cedula=documento,
        nombre=str(payload.get("nombre") or "Paciente").strip(),
        telefono=str(payload.get("telefono") or "").strip(),
        fecha_nacimiento=str(payload.get("fecha_nacimiento") or "").strip(),
        genero=str(payload.get("genero") or "").strip(),
        eps_id=_eps_id(db, str(payload.get("eps") or "Sura")),
    )
    db.add(paciente)
    db.commit()
    db.refresh(paciente)
    return {
        "data": {
            "id": paciente.id,
            "documento": paciente.cedula,
            "nombre": paciente.nombre,
            "telefono": paciente.telefono,
            "eps": _eps_name(db, paciente.eps_id),
        },
        "error": None,
    }


@router.get("/{id}")
def get_paciente(id: str, db: Session = Depends(get_db)):
    raw_id = int(id.replace("pac-", ""))
    paciente = db.query(Paciente).filter(Paciente.id == raw_id).first()
    if not paciente:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    citas = db.query(Cita).filter(Cita.paciente_id == paciente.id).order_by(Cita.fecha_hora.desc()).all()
    consultas = []
    for cita in citas:
        medico = db.query(Medico).filter(Medico.id == cita.medico_id).first()
        historial = db.query(Historial).filter(Historial.consulta_id == cita.id).first()
        consultas.append({
            "id": cita.id,
            "historial_id": historial.id if historial else cita.id,
            "fecha": cita.fecha_hora.isoformat() if cita.fecha_hora else datetime.utcnow().isoformat(),
            "diagnostico": historial.diagnostico if historial else "Seguimiento clinico",
            "medico_nombre": medico.nombre if medico else "Medico",
            "estado": cita.estado,
        })

    return {"data": {**_summary(db, paciente), "consultas": consultas}, "error": None}


@router.get("/{id}/monitor")
def monitor_paciente(id: str, db: Session = Depends(get_db)):
    raw_id = int(id.replace("pac-", ""))
    paciente = db.query(Paciente).filter(Paciente.id == raw_id).first()
    if not paciente:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    citas = db.query(Cita).filter(Cita.paciente_id == paciente.id).all()
    active = [c for c in citas if c.estado in ("programada", "activa", "pendiente", "confirmada")]
    alerts = []
    if not citas:
        alerts.append("Paciente sin citas registradas.")
    if active:
        alerts.append(f"Tiene {len(active)} cita(s) activa(s) o pendientes.")
    if not paciente.eps_id:
        alerts.append("EPS no definida.")

    return {
        "data": {
            "success": True,
            "patient": _summary(db, paciente),
            "appointments": [
                {
                    "id": str(c.id),
                    "fecha_hora": c.fecha_hora.isoformat() if c.fecha_hora else "",
                    "estado": c.estado,
                    "motivo": c.motivo,
                }
                for c in citas
            ],
            "alerts": alerts,
        },
        "error": None,
    }


@router.get("/{id}/historial")
def get_paciente_historial(id: int, db: Session = Depends(get_db)):
    historiales = db.query(Historial).filter(Historial.consulta_id == id).all()
    return {"data": historiales, "error": None}
