"""Utilidades compartidas del agente conversacional."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models.db_models import Cita, EPS, Medico, Paciente
from app.services.slots import SlotsService


def normalize_paciente_id(value: Any) -> int | None:
    if value is None:
        return None
    raw = str(value).strip()
    if raw.startswith("pac-"):
        raw = raw[4:]
    try:
        return int(raw)
    except ValueError:
        return None


def eps_name(db: Session, eps_id: int | None) -> str:
    eps = db.query(EPS).filter(EPS.id == eps_id).first() if eps_id else None
    return eps.nombre if eps else ""


def eps_id(db: Session, eps_name: str | None) -> int:
    name = (eps_name or "Sura").strip() or "Sura"
    eps = db.query(EPS).filter(EPS.nombre == name).first()
    if eps:
        return eps.id
    eps = EPS(nombre=name)
    db.add(eps)
    db.commit()
    db.refresh(eps)
    return eps.id


def patient_summary(db: Session, paciente: Paciente) -> dict[str, Any]:
    citas = db.query(Cita).filter(Cita.paciente_id == paciente.id).all()
    ultima = max((c.fecha_hora for c in citas if c.fecha_hora), default=None)
    return {
        "id": f"pac-{paciente.id}",
        "nombre": paciente.nombre,
        "documento": paciente.cedula,
        "eps": eps_name(db, paciente.eps_id),
        "telefono": paciente.telefono,
        "ultima_consulta": ultima.isoformat() if ultima else "Sin consultas registradas",
        "total_consultas": len(citas),
    }


def pick_value(payload: dict[str, Any], source: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = source.get(key)
        if value is None:
            value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def extract_patient_from_text(text: str) -> dict[str, str]:
    normalized = " ".join(text.replace(",", " ").split())
    lower = normalized.lower()
    name = ""
    for marker in ("paciente", "nombre"):
        idx = lower.find(marker)
        if idx >= 0:
            candidate = normalized[idx + len(marker):].strip(" :-")
            if candidate:
                name = " ".join(candidate.split()[:3]).strip(" .")
                break
    document = ""
    digits = "".join(ch if ch.isdigit() else " " for ch in normalized).split()
    if digits:
        document = max(digits, key=len)
    eps = ""
    eps_idx = lower.find("eps")
    if eps_idx >= 0:
        eps = " ".join(normalized[eps_idx + 3:].strip(" :-").split()[:2]).strip(" .")
    return {"nombre": name, "documento": document, "eps": eps}


def list_medicos(db: Session) -> list[dict[str, Any]]:
    rows = db.query(Medico).order_by(Medico.id.asc()).all()
    data = []
    for medico in rows:
        eps = db.query(EPS).filter(EPS.id == medico.eps_id).first()
        data.append({
            "id": medico.id,
            "nombre": medico.nombre,
            "especialidad": medico.especialidad,
            "eps": eps.nombre if eps else "",
        })
    return data


def list_slots_for_agent(db: Session, medico_id: int, date_str: str | None = None) -> list[dict[str, Any]]:
    """Horarios disponibles vía SlotsService (misma lógica que REST /citas)."""
    svc = SlotsService(db)
    if date_str:
        try:
            day = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            day = datetime.utcnow().date()
    else:
        day = datetime.utcnow().date()

    available: list[dict[str, Any]] = []
    for slot in svc.generate_slots(medico_id, day):
        if not slot.get("available"):
            continue
        available.append({
            "id": slot["id"],
            "datetime": slot["datetime"],
        })
    return available


def resolve_slot_datetime(
    db: Session,
    medico_id: int,
    slot_id: Any,
    target_date: str | None = None,
) -> datetime | None:
    if not slot_id:
        return None
    slot_key = str(slot_id).strip()
    slots = list_slots_for_agent(db, medico_id, target_date)
    selected = next((s for s in slots if str(s["id"]) == slot_key), None)
    if not selected:
        try:
            numeric = int(slot_id)
            selected = next((s for s in slots if str(s.get("id", "")).endswith(f"_{numeric}")), None)
        except (TypeError, ValueError):
            pass
    if not selected:
        return None
    try:
        return datetime.fromisoformat(selected["datetime"])
    except ValueError:
        return None


def extract_date_from_text(text: str) -> str | None:
    """Extrae fecha del texto del usuario (manana, lunes, en 3 dias, etc)."""
    lower = text.lower()
    today = datetime.utcnow().date()
    m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if m:
        return m.group(1)
    if "pasado ma" in lower:
        return (today + timedelta(days=2)).strftime("%Y-%m-%d")
    if "ma\u00f1ana" in lower or "manana" in lower:
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")
    m = re.search(r"en\s+(\d+)\s+d[ií]a", lower)
    if m:
        return (today + timedelta(days=int(m.group(1)))).strftime("%Y-%m-%d")
    m = re.search(r"para\s+(\d+)\s+d[ií]a", lower)
    if m:
        return (today + timedelta(days=int(m.group(1)))).strftime("%Y-%m-%d")
    if "pr\u00f3xima semana" in lower or "proxima semana" in lower or "siguiente semana" in lower:
        return (today + timedelta(days=7)).strftime("%Y-%m-%d")
    days_map = {
        "lunes": 0, "martes": 1, "miercoles": 2, "mi\u00e9rcoles": 2,
        "jueves": 3, "viernes": 4, "sabado": 5, "s\u00e1bado": 5, "domingo": 6,
    }
    for day_name, weekday in days_map.items():
        if day_name in lower:
            days_ahead = (weekday - today.weekday()) % 7 or 7
            return (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    m = re.search(r"(\d{1,2})[/\-](\d{1,2})", text)
    if m:
        day_num, month = int(m.group(1)), int(m.group(2))
        year = today.year
        try:
            candidate = date(year, month, day_num)
            if candidate < today:
                candidate = date(year + 1, month, day_num)
            return candidate.strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def mock_historial(text: str) -> dict[str, Any]:
    return {
        "motivo_consulta": text[:80],
        "sintomas": ["Sintomas descritos en consulta"],
        "diagnostico": "Impresion diagnostica en estudio",
        "plan_tratamiento": "Seguimiento ambulatorio y control clinico.",
        "medicamentos_sugeridos": [],
    }
