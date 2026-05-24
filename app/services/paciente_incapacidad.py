"""Campos de incapacidad en paciente (formato Melanys) y prueba de radicaciones."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.db_models import EPS, IncapacidadRadicacionJob, Paciente

# Campos del PDF de referencia (Melanys Jimenez) usados en OCR / JSON.
PACIENTE_INCAPACIDAD_FIELD_KEYS = (
    "paciente_nombre",
    "paciente_tipo_documento",
    "paciente_numero_documento",
    "tipo_paciente",
    "sexo",
    "fecha_nacimiento",
    "edad_texto",
    "eps_detectada",
    "entidad_codigo",
    "grupo_servicio",
    "modalidad_servicio",
    "origen",
    "causa",
    "incapacidad_retroactiva",
    "prorroga",
)


def _sexo_label(genero: str | None) -> str:
    g = (genero or "").strip().upper()
    if g in {"F", "FEMENINO", "FEM"}:
        return "Femenino"
    if g in {"M", "MASCULINO", "MAS"}:
        return "Masculino"
    return genero or "—"


def _parse_birth_date(value: str | None) -> date | None:
    if not value:
        return None
    raw = value.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _edad_texto(fecha_nacimiento: str | None) -> str:
    born = _parse_birth_date(fecha_nacimiento)
    if not born:
        return "—"
    today = date.today()
    years = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    months = (today.month - born.month) % 12
    days = (today - date(today.year, today.month, min(today.day, born.day))).days % 31
    return f"{years} Años / {months} Meses / {days} Días"


def build_paciente_incapacidad_datos(paciente: Paciente, eps: EPS | None = None) -> dict[str, Any]:
    """JSON de campos del paciente alineados al PDF Melanys / OCR."""
    eps_name = eps.nombre if eps else (paciente.eps.nombre if paciente.eps else "")
    stored = dict(paciente.datos_incapacidad_json or {})
    base = {
        "paciente_nombre": paciente.nombre,
        "paciente_tipo_documento": paciente.tipo_documento or "CC",
        "paciente_numero_documento": paciente.cedula,
        "tipo_paciente": paciente.tipo_paciente or "Contributivo",
        "sexo": _sexo_label(paciente.genero),
        "fecha_nacimiento": paciente.fecha_nacimiento or "",
        "edad_texto": _edad_texto(paciente.fecha_nacimiento),
        "eps_detectada": eps_name,
        "entidad_codigo": stored.get("entidad_codigo") or "",
        "grupo_servicio": stored.get("grupo_servicio") or "ConsultaExterna",
        "modalidad_servicio": stored.get("modalidad_servicio") or "Intramural",
        "origen": stored.get("origen") or "Comun",
        "causa": stored.get("causa") or "",
        "incapacidad_retroactiva": stored.get("incapacidad_retroactiva") or "Ninguna",
        "prorroga": stored.get("prorroga") or "Ninguna",
    }
    base.update({k: v for k, v in stored.items() if v not in (None, "")})
    return base


def sync_paciente_incapacidad_datos(db: Session, paciente: Paciente, eps: EPS | None = None) -> dict[str, Any]:
    datos = build_paciente_incapacidad_datos(paciente, eps)
    paciente.datos_incapacidad_json = datos
    db.commit()
    db.refresh(paciente)
    return datos


def append_radicacion_proof(
    db: Session,
    paciente_id: int,
    job: IncapacidadRadicacionJob,
    *,
    ocr_data: dict[str, Any] | None = None,
) -> None:
    """Guarda en el paciente la prueba de una radicación completada."""
    paciente = db.query(Paciente).filter(Paciente.id == paciente_id).first()
    if not paciente:
        return

    historial = []
    if isinstance(paciente.radicaciones_json, list):
        historial = list(paciente.radicaciones_json)

    entry = {
        "job_id": job.id,
        "historial_id": job.historial_id,
        "numero_incapacidad": (ocr_data or job.ocr_json or {}).get("numero_incapacidad"),
        "estado": job.estado,
        "score": job.score,
        "recomendacion": job.recomendacion,
        "completado_en": job.updated_at.isoformat() if job.updated_at else datetime.utcnow().isoformat(),
        "ocr": job.ocr_json,
        "rethus": job.rethus_json,
        "adres": job.adres_json,
        "reporte": job.reporte_json,
    }
    historial.append(entry)
    paciente.radicaciones_json = historial
    db.commit()
