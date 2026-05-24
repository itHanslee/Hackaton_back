"""Agente conversacional MediNote: tools, intents y respuestas Azure."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from openai import AzureOpenAI
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.database import SessionLocal
from app.models.db_models import Cita, EPS, Medico, Paciente
from app.services.ai import AIService
from app.services.clinical_context import (
    apply_prior_clinical_safety,
    load_patient_clinical_context,
)
from app.services.medicamentos import MedicamentosService

logger = logging.getLogger(__name__)

TOOLS: dict[str, dict[str, str]] = {
    "crear_paciente": {
        "name": "crear_paciente",
        "label": "Creando paciente",
        "description": "Registra un paciente para agendamiento, consulta e historial clinico.",
    },
    "monitor_paciente": {
        "name": "monitor_paciente",
        "label": "Monitoreando paciente",
        "description": "Consulta resumen, citas, historial y alertas operativas de un paciente.",
    },
    "generar_historial": {
        "name": "generar_historial",
        "label": "Generando historial clinico",
        "description": "Genera un historial clinico estructurado desde la transcripcion de la consulta.",
    },
    "buscar_medico": {
        "name": "buscar_medico",
        "label": "Buscando medicos disponibles",
        "description": "Busca medicos y horarios disponibles para agendar cita.",
    },
    "crear_cita": {
        "name": "crear_cita",
        "label": "Creando cita medica",
        "description": "Agenda una nueva cita medica para el paciente.",
    },
    "consulta_medica": {
        "name": "consulta_medica",
        "label": "Analizando consulta",
        "description": "Analiza y responde una consulta medica general.",
    },
}

INTENT_TO_TOOL = {
    "crear_paciente": "crear_paciente",
    "monitor_paciente": "monitor_paciente",
    "generar_historial": "generar_historial",
    "agendar_cita": "buscar_medico",
    "consulta_medica": "buscar_medico",
    "desconocido": "buscar_medico",
}

SYSTEM_PROMPT = (
    "Eres MediNote, asistente administrativo de una plataforma de salud en Colombia. "
    "Tu prioridad absoluta es la veracidad operativa: nunca afirmes que una accion se ejecuto "
    "si no existe confirmacion real en el resultado de la tool.\n\n"
    "Objetivo principal:\n"
    "- Ayudar a agendar citas, consultar disponibilidad, registrar pacientes, monitorear pacientes y "
    "resumir historial clinico de forma simple y confiable.\n\n"
    "Reglas criticas de verdad:\n"
    "- Si el resultado de la tool tiene success=true, puedes afirmar la accion como confirmada.\n"
    "- Si success=false o faltan datos, NO inventes ni supongas valores (nombres, documentos, telefonos, horas, IDs).\n"
    "- Si no hay ejecucion confirmada, dilo claramente: 'Aun no se ha confirmado en el sistema'.\n"
    "- No fabriques IDs, citas, pacientes ni historiales.\n\n"
    "Manejo de datos faltantes (sin ser pesado):\n"
    "- Pide solo los campos realmente faltantes y en un unico mensaje.\n"
    "- No repitas preguntas ya respondidas en el historial.\n"
    "- Si faltan varios datos, listalos juntos en formato corto.\n"
    "- Si el usuario ya dio un dato aproximado, propon confirmacion en vez de volver a pedir desde cero.\n\n"
    "Estilo de conversacion:\n"
    "- Espanol claro, cercano y profesional.\n"
    "- Frases cortas, accionables y faciles de escanear.\n"
    "- Evita tono robotico y evita friccion innecesaria.\n"
    "- Muestra pasos siguientes concretos cuando aplique.\n\n"
    "Limites clinicos:\n"
    "- No diagnosticar, no formular tratamientos ni medicacion.\n"
    "- Si hay sintomas de alarma, sugerir consulta medica presencial o urgencias de forma prudente.\n\n"
    "Formato recomendado de respuesta:\n"
    "1) Estado: Confirmado / Pendiente / Requiere datos.\n"
    "2) Resultado corto basado en tool_result.\n"
    "3) Siguiente paso (solo uno o dos, sin saturar)."
)

_ai = AIService()


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


def classify_intent(text: str) -> str:
    lower = text.lower()
    if any(w in lower for w in ("monitorear paciente", "monitor paciente", "estado del paciente", "seguimiento paciente")):
        return "monitor_paciente"
    if any(w in lower for w in ("crear paciente", "registrar paciente", "nuevo paciente", "alta paciente")):
        return "crear_paciente"
    if any(w in lower for w in ("historial", "generar historial", "registro clinico", "resumen clinico")):
        return "generar_historial"
    if any(
        w in lower
        for w in (
            "cita", "agendar", "agenda", "reservar", "turno",
            "medico", "médico", "medicos", "médicos",
            "doctor", "doctora", "doctores",
            "especialista", "disponib",
        )
    ):
        return "agendar_cita"
    return "consulta_medica"


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


def _patient_summary(db: Session, paciente: Paciente) -> dict[str, Any]:
    citas = db.query(Cita).filter(Cita.paciente_id == paciente.id).all()
    ultima = max((c.fecha_hora for c in citas if c.fecha_hora), default=None)
    return {
        "id": f"pac-{paciente.id}",
        "nombre": paciente.nombre,
        "documento": paciente.cedula,
        "eps": _eps_name(db, paciente.eps_id),
        "telefono": paciente.telefono,
        "ultima_consulta": ultima.isoformat() if ultima else "Sin consultas registradas",
        "total_consultas": len(citas),
    }


def _pick_value(payload: dict[str, Any], source: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = source.get(key)
        if value is None:
            value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _extract_patient_from_text(text: str) -> dict[str, str]:
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


def _list_medicos(db: Session) -> list[dict[str, Any]]:
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


def _list_slots(medico_id: int, date: str | None = None) -> list[dict[str, Any]]:
    base_date = datetime.utcnow()
    if date:
        try:
            base_date = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            pass
    slots = []
    for index, hour in enumerate(range(9, 17)):
        start_time = base_date.replace(hour=hour, minute=0, second=0, microsecond=0)
        slots.append({"id": medico_id * 100 + index + 1, "datetime": start_time.isoformat()})
    return slots


def _mock_historial(text: str) -> dict[str, Any]:
    return {
        "motivo_consulta": text[:80],
        "sintomas": ["Sintomas descritos en consulta"],
        "diagnostico": "Impresion diagnostica en estudio",
        "plan_tratamiento": "Seguimiento ambulatorio y control clinico.",
        "medicamentos_sugeridos": [],
    }


async def _crear_paciente_tool(db: Session, text: str, payload: dict[str, Any]) -> dict[str, Any]:
    paciente_in = payload.get("paciente") or payload.get("patient") or {}
    if not isinstance(paciente_in, dict):
        paciente_in = {}
    extracted = _extract_patient_from_text(text)
    documento = _pick_value(payload, paciente_in, "documento", "cedula", "identificacion") or extracted["documento"]
    nombre = _pick_value(payload, paciente_in, "nombre", "name") or extracted["nombre"]
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
            "eps": _eps_name(db, existing.eps_id),
        }
        return {"success": True, "patient": patient, "created": False}

    paciente = Paciente(
        cedula=documento,
        nombre=nombre,
        telefono=_pick_value(payload, paciente_in, "telefono", "phone"),
        fecha_nacimiento=_pick_value(payload, paciente_in, "fecha_nacimiento", "birth_date"),
        genero=str(payload.get("genero") or paciente_in.get("genero") or "").strip(),
        eps_id=_eps_id(db, _pick_value(payload, paciente_in, "eps") or extracted["eps"]),
    )
    db.add(paciente)
    db.commit()
    db.refresh(paciente)
    patient = {
        "id": f"pac-{paciente.id}",
        "documento": paciente.cedula,
        "nombre": paciente.nombre,
        "telefono": paciente.telefono,
        "eps": _eps_name(db, paciente.eps_id),
    }
    return {"success": True, "patient": patient, "created": True}


async def _buscar_medico_tool(db: Session, text: str, payload: dict[str, Any]) -> dict[str, Any]:
    especialidad = str(payload.get("especialidad") or "").lower()
    medicos = _list_medicos(db)
    filtered = [
        m for m in medicos
        if not especialidad
        or especialidad in str(m.get("especialidad", "")).lower()
        or especialidad in str(m.get("nombre", "")).lower()
    ] or medicos
    if not filtered:
        return {"success": False, "error": "No hay medicos disponibles"}
    medico_id = int(filtered[0]["id"])
    raw_slots = _list_slots(medico_id)
    slots = [
        {
            "id": str(s.get("id")),
            "hora": str(s.get("datetime", ""))[11:16] or "09:00",
            "disponible": True,
            "datetime": s.get("datetime"),
        }
        for s in raw_slots
    ]
    return {"success": True, "medicos": filtered, "slots": slots, "especialidad": especialidad or None}


async def _monitor_paciente_tool(db: Session, text: str, payload: dict[str, Any]) -> dict[str, Any]:
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
            "patients": [_patient_summary(db, p) for p in all_p],
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
        "patient": _patient_summary(db, paciente),
        "appointments": appointments,
        "alerts": alerts,
    }


async def _crear_cita_tool(db: Session, text: str, payload: dict[str, Any]) -> dict[str, Any]:
    paciente_in = payload.get("paciente") or {}
    medico_id = int(payload.get("medico_id") or 1)
    slot_id = int(payload.get("slot_id") or medico_id * 100 + 1)
    paciente_id = normalize_paciente_id(payload.get("paciente_id") or paciente_in.get("id"))

    if not paciente_id:
        return {"success": False, "error": "paciente_id requerido"}

    paciente = db.query(Paciente).filter(Paciente.id == paciente_id).first()
    medico = db.query(Medico).filter(Medico.id == medico_id).first()
    if not paciente:
        return {"success": False, "error": "Paciente no encontrado"}
    if not medico:
        return {"success": False, "error": "Medico no encontrado"}

    slot_index = max(0, (slot_id % 100) - 1)
    fecha_hora = datetime.utcnow().replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(hours=slot_index)
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
    eps = _eps_name(db, paciente.eps_id)
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


async def _generar_historial_tool(
    db: Session, text: str, payload: dict[str, Any]
) -> dict[str, Any]:
    paciente_id = normalize_paciente_id(
        payload.get("paciente_id") or payload.get("patient_id")
    )
    context = None
    prior_rows = []
    paciente = None
    if paciente_id:
        context, prior_rows = load_patient_clinical_context(db, paciente_id)
        paciente = db.query(Paciente).filter(Paciente.id == paciente_id).first()

    try:
        result = await _ai.process_chat(text, generate_historial=True, context=context)
        historial = (
            result.historial.model_dump(mode="json") if result.historial else _mock_historial(text)
        )
        if paciente and prior_rows:
            allergy_terms = apply_prior_clinical_safety(historial, prior_rows)
            historial = MedicamentosService().enrich_historial(
                db, paciente.eps_id, historial, allergy_terms=allergy_terms
            )
        return {"success": True, "historial": historial}
    except Exception as exc:
        logger.warning("generar_historial failed: %s", exc)
        return {"success": True, "historial": _mock_historial(text)}


async def _consulta_medica_tool(text: str) -> dict[str, Any]:
    try:
        result = await _ai.process_chat(text, generate_historial=False)
        return {"success": True, "message": result.message or ""}
    except Exception as exc:
        logger.warning("consulta_medica failed: %s", exc)
        return {"success": True, "message": ""}


async def execute_tool(
    tool_name: str,
    text: str,
    extra_payload: dict[str, Any] | None = None,
    db: Session | None = None,
) -> dict[str, Any]:
    extra_payload = extra_payload or {}
    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        if tool_name == "crear_paciente":
            return await _crear_paciente_tool(db, text, extra_payload)
        if tool_name == "monitor_paciente":
            return await _monitor_paciente_tool(db, text, extra_payload)
        if tool_name == "generar_historial":
            return await _generar_historial_tool(db, text, extra_payload)
        if tool_name == "buscar_medico":
            return await _buscar_medico_tool(db, text, extra_payload)
        if tool_name == "crear_cita":
            return await _crear_cita_tool(db, text, extra_payload)
        return await _consulta_medica_tool(text)
    finally:
        if own_session and db is not None:
            db.close()


def fallback_reply(intent: str, result: dict[str, Any], tool_name: str, text: str) -> str:
    if tool_name == "monitor_paciente" and result.get("patient"):
        p = result["patient"]
        alerts = result.get("alerts") or []
        lines = [
            f"Monitoreo de **{p.get('nombre', 'Paciente')}**",
            f"- Documento: {p.get('documento') or 'No definido'}",
            f"- EPS: {p.get('eps') or 'No definido'}",
            f"- Consultas registradas: {p.get('total_consultas', 0)}",
        ]
        if alerts:
            lines.append("- Alertas: " + " | ".join(alerts))
        return "\n".join(lines)
    if tool_name == "crear_paciente" and result.get("patient"):
        p = result["patient"]
        status = "creado" if result.get("created") else "ya existia"
        return (
            f"Paciente {status}: **{p.get('nombre', 'Paciente')}**\n\n"
            f"- ID: `{p.get('id', '')}`\n"
            f"- Documento: {p.get('documento') or 'No definido'}\n"
            f"- EPS: {p.get('eps') or 'No definido'}"
        )
    if tool_name == "generar_historial" and result.get("historial"):
        return "He generado el historial clinico basado en la consulta."
    if tool_name == "buscar_medico" and result.get("medicos"):
        medicos = result["medicos"]
        slots = result.get("slots", [])[:5]
        lines = [f"Encontre **{len(medicos)} medico(s) disponible(s)**:\n"]
        for m in medicos:
            lines.append(f"- **{m['nombre']}** — {m['especialidad']}")
        if slots:
            horas = ", ".join(s["hora"] for s in slots)
            lines.append(f"\n**Horarios disponibles hoy:** {horas}")
        lines.append("\nDime cual prefieres y te ayudo a agendar la cita.")
        return "\n".join(lines)
    if tool_name == "crear_cita" and result.get("cita"):
        c = result["cita"]
        pac = c.get("paciente", {})
        return (
            f"Cita confirmada (ID: `{c['id']}`)\n\n"
            f"- **Paciente:** {pac.get('nombre', '—')}\n"
            f"- **EPS:** {pac.get('eps', '—')}\n"
            f"- **Medico:** {c['medico']} ({c['especialidad']})\n"
            f"- **Fecha:** {c['fecha']} a las {c['hora']}\n"
        )
    msg = result.get("message", "").strip()
    if msg:
        return msg
    if intent == "agendar_cita":
        return "Te ayudo a agendar. Dime especialidad y fecha preferida."
    if intent == "generar_historial":
        return "Voy a generar el historial clinico con la informacion disponible."
    return f"Entendido. Recibi tu mensaje: {text[:180]}"


def _azure_client(settings: Settings) -> AzureOpenAI | None:
    if not settings.azure_api_key:
        return None
    return AzureOpenAI(
        api_version=settings.azure_openai_api_version,
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_api_key,
    )


def generate_reply(
    intent: str,
    user_text: str,
    tool_name: str,
    tool_result: dict[str, Any],
    conversation_history: list[dict[str, str]] | None = None,
    settings: Settings | None = None,
) -> str:
    settings = settings or get_settings()
    client = _azure_client(settings)
    if client is None:
        return fallback_reply(intent, tool_result, tool_name, user_text)
    try:
        history_snippet = "[]"
        if conversation_history:
            try:
                history_snippet = json.dumps(conversation_history[-12:], ensure_ascii=False)
            except Exception:
                history_snippet = "[]"
        completion = client.chat.completions.create(
            model=settings.azure_openai_deployment,
            max_completion_tokens=1200,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Historial reciente: {history_snippet}\n"
                        f"Usuario: {user_text}\n"
                        f"Intent: {intent}\n"
                        f"Tool: {tool_name}\n"
                        f"Resultado tool: {json.dumps(tool_result, ensure_ascii=False)}\n"
                        "Genera la respuesta final para el usuario."
                    ),
                },
            ],
        )
        content = (completion.choices[0].message.content or "").strip()
        return content or fallback_reply(intent, tool_result, tool_name, user_text)
    except Exception as exc:
        logger.warning("Azure OpenAI error: %s", exc)
        return fallback_reply(intent, tool_result, tool_name, user_text)
