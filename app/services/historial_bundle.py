"""Carga historial + paciente + médico + EPS desde la BD."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.db_models import Cita, Consulta, EPS, Historial, Medico, Paciente


@dataclass
class HistorialBundle:
    historial: Historial
    consulta: Consulta | None
    cita: Cita | None
    paciente: Paciente | None
    medico: Medico | None
    eps: EPS | None


def load_historial_bundle(db: Session, historial_id: int) -> HistorialBundle | None:
    historial = db.query(Historial).filter(Historial.id == historial_id).first()
    if not historial:
        return None

    consulta = db.query(Consulta).filter(Consulta.id == historial.consulta_id).first()
    cita = None
    paciente = None
    medico = None
    eps = None

    if consulta:
        cita = db.query(Cita).filter(Cita.id == consulta.cita_id).first()
        if cita:
            paciente = db.query(Paciente).filter(Paciente.id == cita.paciente_id).first()
            medico = db.query(Medico).filter(Medico.id == cita.medico_id).first()

    if paciente and paciente.eps_id:
        eps = db.query(EPS).filter(EPS.id == paciente.eps_id).first()
    elif medico and medico.eps_id:
        eps = db.query(EPS).filter(EPS.id == medico.eps_id).first()

    return HistorialBundle(
        historial=historial,
        consulta=consulta,
        cita=cita,
        paciente=paciente,
        medico=medico,
        eps=eps,
    )


def medico_owns_historial(db: Session, bundle: HistorialBundle, medico_id: int) -> bool:
    if not bundle.cita:
        return False
    return bundle.cita.medico_id == medico_id


def incapacidad_dias(historial: Historial, override: int | None = None) -> int:
    if override is not None and override > 0:
        return override
    meds = historial.medicamentos_sugeridos or {}
    if isinstance(meds, dict):
        dias = meds.get("incapacidad_dias")
        if dias is not None:
            try:
                return max(int(dias), 1)
            except (TypeError, ValueError):
                pass
    return 3


def incapacidad_fechas(bundle: HistorialBundle, dias: int) -> tuple[date, date]:
    start: date
    if bundle.cita and bundle.cita.fecha_hora:
        start = bundle.cita.fecha_hora.date()
    else:
        start = datetime.utcnow().date()
    end = start + timedelta(days=max(dias - 1, 0))
    return start, end
