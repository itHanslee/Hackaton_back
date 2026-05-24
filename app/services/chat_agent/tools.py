"""Implementación de tools del agente conversacional."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models.db_models import Cita, Medico, Paciente
from app.services.ai import AIService
from app.services.chat_agent.helpers import (
    eps_id,
    eps_name,
    extract_date_from_text,
    extract_patient_from_text,
    list_medicos,
    list_slots_for_agent,
    mock_historial,
    normalize_paciente_id,
    patient_summary,
    pick_value,
    resolve_slot_datetime,
)
from app.services.clinical_context import load_patient_clinical_context
from app.services.clinical_enrichment import enrich_historial_for_patient

logger = logging.getLogger(__name__)
_ai = AIService()


async def crear_paciente_tool(db: Session, text: str, payload: dict[str, Any]) -> dict[str, Any]:
    paciente_in = payload.get("paciente") or payload.get("patient") or {}
    if not isinstance(paciente_in, dict):
        paciente_in = {}
    extracted = extract_patient_from_text(text)
    documento = pick_value(payload, paciente_in, "documento", "cedula", "identificacion") or extracted["documento"]
    nombre = pick_value(payload, paciente_in, "nombre", "name") or extracted["nombre"]
    missing = []
    if not nombre:
        missing.append("nombre")
    if not documento:
        missing.append("documento")
    if missing:
        return {"success": False, "error": "Datos incompletos", "missing_fields": missing}

    existing = db.query(Paciente).filter(Paciente.cedula == documento).first()
    if existing:
        patient = {
            "id": f"pac-{existing.id}",
            "documento": existing.cedula,
            "nombre": existing.nombre,
            "telefono": existing.telefono,
            "eps": eps_name(db, existing.eps_id),
        }
        return {"success": True, "patient": patient, "created": False}

    paciente = Paciente(
        cedula=documento,
        nombre=nombre,
        telefono=pick_value(payload, paciente_in, "telefono", "phone"),
        fecha_nacimiento=pick_value(payload, paciente_in, "fecha_nacimiento", "birth_date"),
        genero=str(payload.get("genero") or paciente_in.get("genero") or "").strip(),
        eps_id=eps_id(db, pick_value(payload, paciente_in, "eps") or extracted["eps"]),
    )
    db.add(paciente)
    db.commit()
    db.refresh(paciente)
    patient = {
        "id": f"pac-{paciente.id}",
        "documento": paciente.cedula,
        "nombre": paciente.nombre,
        "telefono": paciente.telefono,
        "eps": eps_name(db, paciente.eps_id),
    }
    return {"success": True, "patient": patient, "created": True}


async def buscar_medico_tool(db: Session, text: str, payload: dict[str, Any]) -> dict[str, Any]:
    especialidad = str(payload.get("especialidad") or "").lower()
    target_date = (
        str(payload.get("fecha") or payload.get("date") or "").strip()
        or extract_date_from_text(text)
    )
    medicos = list_medicos(db)
    filtered = [
        m for m in medicos
        if not especialidad
        or especialidad in str(m.get("especialidad", "")).lower()
        or especialidad in str(m.get("nombre", "")).lower()
    ] or medicos
    if not filtered:
        return {"success": False, "error": "No hay medicos disponibles"}
    medico_id = int(filtered[0]["id"])
    raw_slots = list_slots_for_agent(db, medico_id, target_date)
    if not raw_slots:
        for offset in range(1, 6):
            next_date = (datetime.utcnow().date() + timedelta(days=offset)).strftime("%Y-%m-%d")
            raw_slots = list_slots_for_agent(db, medico_id, next_date)
            if raw_slots:
                target_date = next_date
                break
    slots = [
        {
            "id": str(s.get("id")),
            "hora": str(s.get("datetime", ""))[11:16] or "09:00",
            "disponible": True,
            "datetime": s.get("datetime"),
        }
        for s in raw_slots
    ]
    return {
        "success": True,
        "medicos": filtered,
        "slots": slots,
        "especialidad": especialidad or None,
        "fecha_consultada": target_date or datetime.utcnow().strftime("%Y-%m-%d"),
        "fuente_disponibilidad": "database",
    }


async def monitor_paciente_tool(db: Session, text: str, payload: dict[str, Any]) -> dict[str, Any]:
    patient_id = normalize_paciente_id(
        payload.get("paciente_id") or payload.get("patient_id") or payload.get("id")
    )
    if not patient_id:
        documento = str(payload.get("documento") or payload.get("cedula") or "").strip()
        if documento:
            paciente = db.query(Paciente).filter(Paciente.cedula == documento).first()
        else:
            paciente = None
    else:
        paciente = db.query(Paciente).filter(Paciente.id == patient_id).first()

    if not paciente:
        all_p = db.query(Paciente).order_by(Paciente.id.desc()).limit(10).all()
        return {
            "success": False,
            "error": "Paciente no encontrado",
            "patients": [patient_summary(db, p) for p in all_p],
        }

    citas = db.query(Cita).filter(Cita.paciente_id == paciente.id).all()
    active = [c for c in citas if c.estado in ("programada", "activa", "pendiente", "confirmada")]
    alerts = []
    if not citas:
        alerts.append("Paciente sin citas registradas.")
    if active:
        alerts.append(f"Tiene {len(active)} cita(s) activa(s) o pendientes.")
    if not paciente.eps_id:
        alerts.append("EPS no definida.")

    appointments = [
        {
            "id": str(c.id),
            "fecha_hora": c.fecha_hora.isoformat() if c.fecha_hora else "",
            "estado": c.estado,
            "motivo": c.motivo,
        }
        for c in citas
    ]
    return {
        "success": True,
        "patient": patient_summary(db, paciente),
        "appointments": appointments,
        "alerts": alerts,
    }


async def crear_cita_tool(db: Session, text: str, payload: dict[str, Any]) -> dict[str, Any]:
    paciente_in = payload.get("paciente") or {}
    medico_id = int(payload.get("medico_id") or 0)
    slot_id = payload.get("slot_id")
    if not medico_id:
        return {"success": False, "error": "medico_id requerido (use buscar_medico primero)"}
    paciente_id = normalize_paciente_id(payload.get("paciente_id") or paciente_in.get("id"))

    if not paciente_id:
        documento = pick_value(payload, paciente_in, "documento", "cedula", "identificacion")
        if documento:
            existing = db.query(Paciente).filter(Paciente.cedula == documento).first()
            if existing:
                paciente_id = existing.id
            else:
                nombre = pick_value(payload, paciente_in, "nombre", "name")
                if nombre:
                    new_p = Paciente(
                        cedula=documento,
                        nombre=nombre,
                        telefono=pick_value(payload, paciente_in, "telefono", "phone"),
                        eps_id=eps_id(db, pick_value(payload, paciente_in, "eps")),
                    )
                    db.add(new_p)
                    db.commit()
                    db.refresh(new_p)
                    paciente_id = new_p.id

    if not paciente_id:
        return {"success": False, "error": "paciente_id requerido (o documento+nombre para crear/ubicar paciente)"}

    paciente = db.query(Paciente).filter(Paciente.id == paciente_id).first()
    medico = db.query(Medico).filter(Medico.id == medico_id).first()
    if not paciente:
        return {"success": False, "error": "Paciente no encontrado"}
    if not medico:
        return {"success": False, "error": "Medico no encontrado"}

    fecha_hora: datetime | None = None
    slot_datetime = payload.get("slot_datetime") or payload.get("fecha_hora")
    if slot_datetime:
        try:
            fecha_hora = datetime.fromisoformat(str(slot_datetime).replace("Z", "+00:00"))
            if fecha_hora.tzinfo:
                fecha_hora = fecha_hora.replace(tzinfo=None)
        except ValueError:
            return {"success": False, "error": "slot_datetime inválido"}

    if fecha_hora is None and slot_id:
        target_date = payload.get("fecha") or payload.get("date")
        if isinstance(target_date, str) and "T" in target_date:
            target_date = target_date.split("T")[0]
        fecha_hora = resolve_slot_datetime(
            db,
            medico_id,
            slot_id,
            target_date if isinstance(target_date, str) else None,
        )

    if fecha_hora is None:
        return {"success": False, "error": "Slot no disponible; use buscar_medico y seleccione un horario"}

    cita = Cita(
        paciente_id=paciente.id,
        medico_id=medico.id,
        fecha_hora=fecha_hora,
        motivo=str(payload.get("motivo") or text[:100] or "Consulta general"),
        estado="programada",
    )
    db.add(cita)
    db.commit()
    db.refresh(cita)
    eps = eps_name(db, paciente.eps_id)
    return {
        "success": True,
        "cita": {
            "id": f"cita-{cita.id}",
            "paciente": {"nombre": paciente.nombre, "documento": paciente.cedula, "eps": eps},
            "medico": medico.nombre,
            "especialidad": medico.especialidad,
            "fecha": fecha_hora.strftime("%Y-%m-%d"),
            "hora": fecha_hora.strftime("%H:%M"),
            "estado": cita.estado,
        },
    }


async def generar_historial_tool(db: Session, text: str, payload: dict[str, Any]) -> dict[str, Any]:
    paciente_id = normalize_paciente_id(
        payload.get("paciente_id") or payload.get("patient_id")
    )
    context = None
    if paciente_id:
        context, _ = load_patient_clinical_context(db, paciente_id)

    try:
        result = await _ai.process_chat(text, generate_historial=True, context=context)
        historial = (
            result.historial.model_dump(mode="json") if result.historial else mock_historial(text)
        )
        if paciente_id:
            historial = enrich_historial_for_patient(db, paciente_id, historial)
        return {"success": True, "historial": historial}
    except Exception as exc:
        logger.warning("generar_historial failed: %s", exc)
        return {"success": False, "error": "No se pudo generar el historial clínico", "historial": None}


async def consulta_medica_tool(text: str) -> dict[str, Any]:
    try:
        result = await _ai.process_chat(text, generate_historial=False)
        return {"success": True, "message": result.message or ""}
    except Exception as exc:
        logger.warning("consulta_medica failed: %s", exc)
        return {"success": False, "error": "No se pudo procesar la consulta médica", "message": ""}
