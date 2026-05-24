import asyncio
import base64
import json
import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import AzureOpenAI

load_dotenv()
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"), override=False)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="MediNote Chatbot Backend", version="2.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BE1_URL = os.getenv("BE1_URL", "http://localhost:8000")
GENERAL_BACKEND_URL = os.getenv("GENERAL_BACKEND_URL", "http://localhost:8000")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "https://scia.cognitiveservices.azure.com/")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-5.3-chat")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
AZURE_API_KEY = os.getenv("AZURE_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_STT_MODEL = os.getenv("GROQ_STT_MODEL", "whisper-large-v3-turbo")
GROQ_STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

# HTTP client persistente => evita coste de TLS handshake en cada request (clave para latencia mínima)
_http_client: httpx.AsyncClient | None = None

azure_client: AzureOpenAI | None = None
if AZURE_API_KEY:
    azure_client = AzureOpenAI(
        api_version=AZURE_OPENAI_API_VERSION,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_API_KEY,
    )
else:
    logger.warning("AZURE_API_KEY not found. Using local fallback replies.")

_appointments: list[dict[str, Any]] = [
    {
        "id": "apt-001",
        "paciente": "Carlos Rodriguez",
        "medico": "Dr. Ana Garcia",
        "especialidad": "Cardiologia",
        "fecha": (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"),
        "hora": "09:00",
        "motivo": "Control tension arterial",
        "estado": "pendiente",
    },
    {
        "id": "apt-002",
        "paciente": "Maria Lopez",
        "medico": "Dr. Juan Perez",
        "especialidad": "Medicina General",
        "fecha": (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"),
        "hora": "10:30",
        "motivo": "Consulta dolor de cabeza",
        "estado": "pendiente",
    },
]

_patients: list[dict[str, Any]] = [
    {
        "id": "pac-001",
        "nombre": "Carlos Rodriguez",
        "documento": "100000001",
        "telefono": "3000000001",
        "eps": "Sura",
        "fecha_nacimiento": "",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    },
    {
        "id": "pac-002",
        "nombre": "Maria Lopez",
        "documento": "100000002",
        "telefono": "3000000002",
        "eps": "Nueva EPS",
        "fecha_nacimiento": "",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    },
]

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

# Mock de medicos disponibles
_medicos: list[dict] = [
    {"id": "med-001", "nombre": "Dr. Ana Garcia", "especialidad": "Cardiologia", "disponible": True},
    {"id": "med-002", "nombre": "Dr. Juan Perez", "especialidad": "Medicina General", "disponible": True},
    {"id": "med-003", "nombre": "Dr. Laura Mendez", "especialidad": "Pediatria", "disponible": True},
    {"id": "med-004", "nombre": "Dr. Carlos Rios", "especialidad": "Neurologia", "disponible": False},
    {"id": "med-005", "nombre": "Dr. Sandra Torres", "especialidad": "Cardiologia", "disponible": True},
]


def _mock_historial(text: str) -> dict[str, Any]:
    return {
        "motivo_consulta": text[:80],
        "sintomas": ["Sintomas descritos en consulta"],
        "diagnostico": "Impresion diagnostica en estudio",
        "plan_tratamiento": "Seguimiento ambulatorio y control clinico.",
        "medicamentos_sugeridos": [],
    }


def _classify_intent_local(text: str) -> str:
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


async def execute_tool(tool_name: str, text: str, extra_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    extra_payload = extra_payload or {}
    if tool_name == "crear_paciente":
        return await _crear_paciente_tool(text, extra_payload)

    if tool_name == "monitor_paciente":
        return await _monitor_paciente_tool(text, extra_payload)

    if tool_name == "generar_historial":
        async with httpx.AsyncClient(timeout=45.0) as client:
            try:
                resp = await client.post(f"{BE1_URL}/chat", json={"text": text, "generate_historial": True})
                resp.raise_for_status()
                data = resp.json().get("data", {})
                return {"success": True, "historial": data.get("historial") or _mock_historial(text)}
            except Exception:
                return {"success": True, "historial": _mock_historial(text), "source": "fallback"}

    if tool_name == "buscar_medico":
        return await _buscar_medico_tool(text, extra_payload)

    if tool_name == "crear_cita":
        return await _crear_cita_tool(text, extra_payload)

    async with httpx.AsyncClient(timeout=45.0) as client:
        try:
            resp = await client.post(f"{BE1_URL}/chat", json={"text": text, "generate_historial": False})
            resp.raise_for_status()
            data = resp.json().get("data", {})
            return {"success": True, "message": data.get("message", "")}
        except Exception:
            return {"success": True, "message": ""}


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
    markers = ("paciente", "nombre")
    for marker in markers:
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


def _frontend_medico_id(medico: dict[str, Any]) -> int:
    raw = str(medico.get("id", "0")).replace("med-", "")
    try:
        return int(raw)
    except ValueError:
        return 0


def _frontend_patient_id(patient: dict[str, Any]) -> str:
    return str(patient.get("id", ""))


def _patient_summary(patient: dict[str, Any]) -> dict[str, Any]:
    patient_id = _frontend_patient_id(patient)
    consultas = [a for a in _appointments if str(a.get("paciente_id", "")) == patient_id or _appointment_patient_name(a) == patient.get("nombre")]
    last = max((a.get("fecha_hora") or f"{a.get('fecha', '')}T{a.get('hora', '00:00')}" for a in consultas), default="")
    return {
        "id": patient_id,
        "nombre": patient.get("nombre", "Paciente"),
        "documento": patient.get("documento", ""),
        "eps": patient.get("eps", ""),
        "telefono": patient.get("telefono", ""),
        "ultima_consulta": last or "Sin consultas registradas",
        "total_consultas": len(consultas),
    }


def _appointment_patient_name(appointment: dict[str, Any]) -> str:
    patient = appointment.get("paciente")
    if isinstance(patient, dict):
        return str(patient.get("nombre", "Paciente"))
    return str(patient or "Paciente")


def _appointment_calendar(appointment: dict[str, Any]) -> dict[str, Any]:
    patient_id = str(appointment.get("paciente_id") or "")
    patient_name = _appointment_patient_name(appointment)
    patient = next((p for p in _patients if p.get("id") == patient_id or p.get("nombre") == patient_name), None)
    medico_id = appointment.get("medico_id")
    medico = next((m for m in _medicos if m.get("id") == medico_id), None)
    fecha_hora = appointment.get("fecha_hora") or f"{appointment.get('fecha', '')}T{appointment.get('hora', '09:00')}:00"
    return {
        "id": str(appointment.get("id", "")),
        "paciente_id": patient_id or (patient.get("id") if patient else ""),
        "paciente_nombre": patient_name,
        "paciente_documento": patient.get("documento", "") if patient else "",
        "paciente_eps": patient.get("eps", "") if patient else "",
        "medico_id": _frontend_medico_id(medico or {"id": medico_id or "0"}),
        "medico_nombre": appointment.get("medico") or (medico.get("nombre") if medico else "Medico"),
        "especialidad": appointment.get("especialidad") or (medico.get("especialidad") if medico else "General"),
        "fecha_hora": fecha_hora,
        "estado": appointment.get("estado", "programada"),
        "motivo": appointment.get("motivo", ""),
        "historial_id": appointment.get("historial_id", 1),
    }


def _find_patient(payload: dict[str, Any], text: str = "") -> dict[str, Any] | None:
    patient_id = str(payload.get("paciente_id") or payload.get("patient_id") or payload.get("id") or "").strip()
    documento = str(payload.get("documento") or payload.get("cedula") or "").strip()
    lower = text.lower()
    if patient_id:
        found = next((p for p in _patients if str(p.get("id")) == patient_id), None)
        if found:
            return found
    if documento:
        found = next((p for p in _patients if str(p.get("documento")) == documento), None)
        if found:
            return found
    return next((p for p in _patients if p.get("nombre", "").lower() in lower), None)


async def _crear_paciente_tool(text: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Registra paciente desde payload estructurado o desde texto libre."""
    paciente_in = payload.get("paciente") or payload.get("patient") or {}
    if not isinstance(paciente_in, dict):
        paciente_in = {}

    extracted = _extract_patient_from_text(text)
    documento = _pick_value(payload, paciente_in, "documento", "cedula", "identificacion") or extracted["documento"]

    paciente = {
        "nombre": _pick_value(payload, paciente_in, "nombre", "name") or extracted["nombre"] or "Paciente",
        "documento": documento,
        "telefono": _pick_value(payload, paciente_in, "telefono", "phone"),
        "eps": _pick_value(payload, paciente_in, "eps") or extracted["eps"],
        "fecha_nacimiento": _pick_value(payload, paciente_in, "fecha_nacimiento", "birth_date"),
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.post(f"{GENERAL_BACKEND_URL}/pacientes", json=paciente)
            resp.raise_for_status()
            data = resp.json().get("data", {})
            return {"success": True, "patient": data, "created": True}
        except Exception as exc:
            logger.warning("crear_paciente via general backend failed: %s", exc)
            paciente["id"] = f"pac-{uuid.uuid4().hex[:6]}"
            _patients.append(paciente)
            return {"success": True, "patient": paciente, "created": True, "source": "fallback"}


async def _buscar_medico_tool(text: str, payload: dict[str, Any]) -> dict[str, Any]:
    especialidad = str(payload.get("especialidad") or "").lower()
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            medicos_resp = await client.get(f"{GENERAL_BACKEND_URL}/medicos")
            medicos_resp.raise_for_status()
            medicos = medicos_resp.json().get("data", [])
            filtered = [
                m for m in medicos
                if not especialidad or especialidad in str(m.get("especialidad", "")).lower() or especialidad in str(m.get("nombre", "")).lower()
            ] or medicos
            medico_id = filtered[0]["id"] if filtered else 1
            slots_resp = await client.get(f"{GENERAL_BACKEND_URL}/medicos/{medico_id}/slots")
            slots_resp.raise_for_status()
            slots = [
                {
                    "id": str(s.get("id")),
                    "hora": str(s.get("datetime", ""))[11:16] or "09:00",
                    "disponible": True,
                    "datetime": s.get("datetime"),
                }
                for s in slots_resp.json().get("data", [])
            ]
            return {"success": True, "medicos": filtered, "slots": slots, "especialidad": especialidad or None}
        except Exception as exc:
            logger.warning("buscar_medico via general backend failed: %s", exc)
            text_lower = text.lower()
            filtered = [
                m for m in _medicos
                if m["disponible"] and m["especialidad"].lower() in text_lower
            ] or [m for m in _medicos if m["disponible"]]
            slots = [{"id": f"slot-{h:02d}00", "hora": f"{h:02d}:00", "disponible": True} for h in range(8, 17)]
            return {"success": True, "medicos": filtered, "slots": slots, "source": "fallback"}


async def _monitor_paciente_tool(text: str, payload: dict[str, Any]) -> dict[str, Any]:
    patient_id = str(payload.get("paciente_id") or payload.get("patient_id") or payload.get("id") or "").strip()
    if patient_id:
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.get(f"{GENERAL_BACKEND_URL}/pacientes/{patient_id}/monitor")
                resp.raise_for_status()
                return resp.json().get("data", {})
            except Exception as exc:
                logger.warning("monitor_paciente via general backend failed: %s", exc)

    patient = _find_patient(payload, text)
    if not patient:
        return {"success": False, "error": "Paciente no encontrado", "patients": [_patient_summary(p) for p in _patients]}

    patient_id = _frontend_patient_id(patient)
    appointments = [
        _appointment_calendar(a)
        for a in _appointments
        if str(a.get("paciente_id", "")) == patient_id or _appointment_patient_name(a) == patient.get("nombre")
    ]
    active = [a for a in appointments if a.get("estado") in ("activa", "pendiente", "programada", "confirmada")]
    alerts = []
    if not appointments:
        alerts.append("Paciente sin citas registradas.")
    if active:
        alerts.append(f"Tiene {len(active)} cita(s) activas o pendientes.")
    if not patient.get("eps"):
        alerts.append("EPS no definida.")

    return {
        "success": True,
        "patient": _patient_summary(patient),
        "appointments": appointments,
        "alerts": alerts,
    }


async def _crear_cita_tool(text: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Crea una cita. Acepta payload completo con paciente + medico + slot."""
    paciente_in = payload.get("paciente") or {}
    medico_id = payload.get("medico_id")
    slot_id = payload.get("slot_id")
    paciente_id = payload.get("paciente_id") or paciente_in.get("id")

    if paciente_id and medico_id and slot_id:
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.post(
                    f"{GENERAL_BACKEND_URL}/citas",
                    json={
                        "paciente_id": paciente_id,
                        "medico_id": medico_id,
                        "slot_id": slot_id,
                        "motivo": text[:100] or "Consulta general",
                    },
                )
                resp.raise_for_status()
                data = resp.json().get("data", {})
                return {"success": True, "cita": data}
            except Exception as exc:
                logger.warning("crear_cita via general backend failed: %s", exc)

    # Resolver medico
    medico = next((m for m in _medicos if m["id"] == medico_id), None)
    if not medico:
        # Fallback: primer medico disponible
        medico = next((m for m in _medicos if m["disponible"]), _medicos[0])

    # Resolver slot
    hora = "09:00"
    if isinstance(slot_id, str) and slot_id.startswith("slot-"):
        try:
            h = int(slot_id.split("-")[1][:2])
            hora = f"{h:02d}:00"
        except Exception:
            pass

    fecha = payload.get("fecha") or (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    cita = {
        "id": f"apt-{uuid.uuid4().hex[:6]}",
        "paciente": {
            "nombre": paciente_in.get("nombre") or "Paciente",
            "documento": paciente_in.get("documento") or "",
            "telefono": paciente_in.get("telefono") or "",
            "eps": paciente_in.get("eps") or "",
        },
        "medico_id": medico["id"],
        "medico": medico["nombre"],
        "especialidad": medico["especialidad"],
        "slot_id": slot_id or "",
        "fecha": fecha,
        "hora": hora,
        "motivo": text[:100] or "Consulta general",
        "estado": "confirmada",
        "creada_en": datetime.now().isoformat(timespec="seconds"),
    }
    _appointments.append(cita)
    return {"success": True, "cita": cita}


def _fallback_reply(intent: str, result: dict[str, Any], tool_name: str, text: str) -> str:
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
        lines = [f"Encontré **{len(medicos)} médico(s) disponible(s)**:\n"]
        for m in medicos:
            lines.append(f"- **{m['nombre']}** — {m['especialidad']}")
        if slots:
            horas = ", ".join(s["hora"] for s in slots)
            lines.append(f"\n**Horarios disponibles hoy:** {horas}")
        lines.append("\nDime cuál prefieres y te ayudo a agendar la cita.")
        return "\n".join(lines)
    if tool_name == "crear_cita" and result.get("cita"):
        c = result["cita"]
        pac = c.get("paciente", {})
        return (
            f"✅ **Cita confirmada** (ID: `{c['id']}`)\n\n"
            f"- **Paciente:** {pac.get('nombre','—')}\n"
            f"- **EPS:** {pac.get('eps','—')}\n"
            f"- **Médico:** {c['medico']} ({c['especialidad']})\n"
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


def _azure_reply(intent: str, user_text: str, tool_name: str, tool_result: dict[str, Any]) -> str:
    if azure_client is None:
        return _fallback_reply(intent, tool_result, tool_name, user_text)
    try:
        completion = azure_client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            max_completion_tokens=1200,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Eres MediNote, el asistente virtual de la clinica MediNote. "
                        "Tu rol principal es ayudar a los pacientes con tareas administrativas: "
                        "agendar citas, mostrar medicos disponibles, consultar horarios, revisar "
                        "su historial clinico y orientar sobre el funcionamiento de la clinica. "
                        "\n\nQUE PUEDES hacer: "
                        "- Agendar y confirmar citas medicas. "
                        "- Mostrar especialistas disponibles y sus horarios. "
                        "- Resumir el historial clinico del paciente cuando este lo pida. "
                        "- Informar sobre medicamentos cubiertos por su EPS. "
                        "- Dar orientacion general sobre cuando consultar a un medico. "
                        "\n\nQUE NO debes hacer: "
                        "- NO actues como medico: no des diagnosticos, no recetes ni indiques tratamientos. "
                        "- NO ofrezcas 'iniciar una consulta medica' como si fueras un doctor virtual. "
                        "- Si el paciente describe sintomas concretos, sugierele agendar una cita con el "
                        "especialista adecuado en lugar de intentar diagnosticar. "
                        "\n\nEstilo: "
                        "- Responde en espanol claro, breve y profesional, con tono cercano. "
                        "- Si el usuario ya entrego datos (nombre, fecha, preferencia), NO los repreguntes. "
                        "- Cuando una tool ya te dio la informacion (medicos, horarios, cita creada), "
                        "presentala directamente, sin volver a preguntar lo mismo. "
                        "- Antes de crear definitivamente una cita, repite los datos clave (medico, "
                        "fecha, hora, EPS) y pide confirmacion final."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Usuario: {user_text}\n"
                        f"Intent: {intent}\n"
                        f"Tool: {tool_name}\n"
                        f"Resultado tool: {json.dumps(tool_result, ensure_ascii=False)}\n"
                        "Genera la respuesta final para el usuario."
                    ),
                },
            ],
        )
        content = completion.choices[0].message.content or ""
        content = content.strip()
        return content or _fallback_reply(intent, tool_result, tool_name, user_text)
    except Exception as exc:
        logger.warning("Azure OpenAI error: %s", exc)
        return _fallback_reply(intent, tool_result, tool_name, user_text)


@app.on_event("startup")
async def _startup():
    global _http_client
    # HTTP/2 + keep-alive => latencia mínima en llamadas a Groq
    _http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=5.0),
        limits=httpx.Limits(max_keepalive_connections=20, max_connections=40),
        http2=False,  # Groq no soporta h2 oficialmente, h1 keep-alive es óptimo
    )


@app.on_event("shutdown")
async def _shutdown():
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "be1": BE1_URL,
        "azure_configured": bool(AZURE_API_KEY),
        "azure_endpoint": AZURE_OPENAI_ENDPOINT,
        "azure_deployment": AZURE_OPENAI_DEPLOYMENT,
        "groq_configured": bool(GROQ_API_KEY),
        "groq_model": GROQ_STT_MODEL,
    }


class TranscribeJSONRequest(BaseModel):
    audio: str            # base64 (sin prefijo data:)
    mime_type: str = "audio/webm"
    language: str | None = "es"
    prompt: str | None = None


async def _groq_transcribe(audio_bytes: bytes, mime_type: str, language: str | None, prompt: str | None) -> dict[str, Any]:
    if not GROQ_API_KEY:
        raise HTTPException(status_code=503, detail="GROQ_API_KEY no configurada")
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Audio vacio")
    if _http_client is None:
        raise HTTPException(status_code=500, detail="HTTP client no inicializado")

    # Inferir extensión a partir del mime; Groq necesita un nombre de archivo
    ext = "webm"
    if "ogg" in mime_type: ext = "ogg"
    elif "wav" in mime_type: ext = "wav"
    elif "mp3" in mime_type or "mpeg" in mime_type: ext = "mp3"
    elif "mp4" in mime_type or "m4a" in mime_type: ext = "m4a"
    elif "flac" in mime_type: ext = "flac"

    files = {"file": (f"audio.{ext}", audio_bytes, mime_type)}
    data: dict[str, str] = {
        "model": GROQ_STT_MODEL,
        "response_format": "json",
        "temperature": "0",
    }
    if language:
        data["language"] = language
    if prompt:
        data["prompt"] = prompt

    headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
    try:
        resp = await _http_client.post(GROQ_STT_URL, headers=headers, files=files, data=data)
    except httpx.HTTPError as exc:
        logger.warning("Groq STT network error: %s", exc)
        raise HTTPException(status_code=502, detail=f"Error de red Groq: {exc}")

    if resp.status_code >= 400:
        logger.warning("Groq STT %s: %s", resp.status_code, resp.text[:300])
        raise HTTPException(status_code=resp.status_code, detail=f"Groq STT: {resp.text[:200]}")

    try:
        payload = resp.json()
    except Exception:
        raise HTTPException(status_code=500, detail="Respuesta Groq invalida")

    return {"transcript": (payload.get("text") or "").strip(), "raw": payload}


@app.post("/transcribe")
async def transcribe_endpoint(
    file: UploadFile | None = File(default=None),
    language: str | None = Form(default="es"),
    prompt: str | None = Form(default=None),
):
    """STT multipart: ideal para máxima velocidad (sin overhead de base64)."""
    if file is None:
        raise HTTPException(status_code=400, detail="Adjunta 'file' (multipart) o usa /transcribe/json")
    audio_bytes = await file.read()
    mime = file.content_type or "audio/webm"
    result = await _groq_transcribe(audio_bytes, mime, language, prompt)
    return {"data": result, "error": None}


@app.post("/transcribe/json")
async def transcribe_json(req: TranscribeJSONRequest):
    """STT vía JSON+base64 (compatible con el cliente actual)."""
    try:
        audio_bytes = base64.b64decode(req.audio, validate=False)
    except Exception:
        raise HTTPException(status_code=400, detail="Base64 invalido")
    result = await _groq_transcribe(audio_bytes, req.mime_type, req.language, req.prompt)
    return {"data": result, "error": None}


@app.get("/appointments")
async def get_appointments():
    return {"data": _appointments, "error": None}


@app.get("/patients")
async def get_patients():
    return {"data": _patients, "error": None}


@app.get("/pacientes")
async def list_pacientes():
    return {"data": [_patient_summary(p) for p in _patients], "error": None}


@app.post("/pacientes")
async def create_paciente(payload: dict[str, Any]):
    result = await _crear_paciente_tool("", {"paciente": payload})
    patient = result["patient"]
    frontend_id = int(str(patient["id"]).replace("pac-", "")[:6], 16) if patient["id"].startswith("pac-") else len(_patients)
    return {"data": {"id": frontend_id, **patient}, "error": None}


@app.get("/pacientes/{paciente_id}")
async def get_paciente(paciente_id: str):
    patient = _find_patient({"paciente_id": paciente_id})
    if not patient:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")
    monitor = await _monitor_paciente_tool("", {"paciente_id": paciente_id})
    consultas = [
        {
            "id": index + 1,
            "historial_id": a.get("historial_id") or index + 1,
            "fecha": a.get("fecha_hora", ""),
            "diagnostico": "Seguimiento clinico",
            "medico_nombre": a.get("medico_nombre", ""),
            "estado": a.get("estado", "programada"),
        }
        for index, a in enumerate(monitor.get("appointments", []))
    ]
    return {"data": {**_patient_summary(patient), "consultas": consultas}, "error": None}


@app.get("/pacientes/{paciente_id}/monitor")
async def monitor_paciente_endpoint(paciente_id: str):
    result = await _monitor_paciente_tool("", {"paciente_id": paciente_id})
    status = 200 if result.get("success") else 404
    if status == 404:
        raise HTTPException(status_code=404, detail=result.get("error", "Paciente no encontrado"))
    return {"data": result, "error": None}


@app.get("/medicos")
async def list_medicos():
    data = [
        {
            "id": _frontend_medico_id(m),
            "nombre": m["nombre"],
            "especialidad": m["especialidad"],
            "eps": "Sura",
        }
        for m in _medicos
        if m.get("disponible")
    ]
    return {"data": data, "error": None}


@app.get("/medicos/{medico_id}/slots")
async def list_slots(medico_id: int):
    base = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)
    slots = []
    for i in range(6):
        dt = base + timedelta(days=i % 3, hours=(i % 4) * 2)
        slots.append({"id": medico_id * 100 + i + 1, "datetime": dt.isoformat()})
    return {"data": slots, "error": None}


@app.get("/citas/calendario")
async def list_citas_calendario(medico_id: int | None = None):
    data = [_appointment_calendar(a) for a in _appointments]
    if medico_id:
        data = [a for a in data if a.get("medico_id") == medico_id]
    return {"data": data, "error": None}


@app.get("/citas/{cita_id}")
async def get_cita(cita_id: str):
    cita = next((a for a in _appointments if str(a.get("id")) == cita_id), None)
    if not cita:
        raise HTTPException(status_code=404, detail="Cita no encontrada")
    return {"data": _appointment_calendar(cita), "error": None}


@app.post("/citas")
async def create_cita(payload: dict[str, Any]):
    patient_id = str(payload.get("paciente_id", ""))
    patient = _find_patient({"paciente_id": patient_id}) or (_patients[0] if _patients else {})
    medico_id = payload.get("medico_id")
    slot_id = payload.get("slot_id")
    result = await _crear_cita_tool(
        str(payload.get("motivo") or "Consulta general"),
        {
            "paciente": patient,
            "paciente_id": patient.get("id"),
            "medico_id": f"med-{int(medico_id):03d}" if isinstance(medico_id, int) else medico_id,
            "slot_id": f"slot-{int(slot_id) % 100:02d}00" if isinstance(slot_id, int) else slot_id,
            "fecha": payload.get("fecha"),
        },
    )
    cita = result["cita"]
    cita["paciente_id"] = patient.get("id", patient_id)
    cita["fecha_hora"] = f"{cita.get('fecha')}T{cita.get('hora')}:00"
    cita["historial_id"] = len(_appointments) + 1
    return {
        "data": {
            "id": len(_appointments),
            "paciente_id": payload.get("paciente_id"),
            "medico_id": payload.get("medico_id"),
            "slot_id": payload.get("slot_id"),
            "historial_id": cita["historial_id"],
            "estado": "confirmada",
        },
        "error": None,
    }


@app.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            text = data.get("text", "")
            force_historial = data.get("generate_historial", False)

            tool_hint = data.get("tool_hint", "")
            intent = _classify_intent_local(text)
            if force_historial:
                intent = "generar_historial"

            # tool_hint permite que el frontend fuerce una tool concreta
            if tool_hint and tool_hint in TOOLS:
                tool_name = tool_hint
            else:
                tool_name = INTENT_TO_TOOL.get(intent, "consulta_medica")
            tool_info = TOOLS[tool_name]
            tool_id = f"tool-{uuid.uuid4().hex[:8]}"

            await websocket.send_json({
                "type": "tool_start",
                "tool": {"id": tool_id, "name": tool_name, "label": tool_info["label"]},
            })

            result = await execute_tool(tool_name, text, extra_payload=data)

            await websocket.send_json({
                "type": "tool_result",
                "tool_id": tool_id,
                "success": result.get("success", False),
                "result": result,
            })

            reply = _azure_reply(intent, text, tool_name, result)
            for i, word in enumerate(reply.split(" ")):
                chunk = word + (" " if i < len(reply.split(" ")) - 1 else "")
                await websocket.send_json({"type": "chunk", "text": chunk})
                await asyncio.sleep(0.02)

            await websocket.send_json({
                "type": "done",
                "intent": intent,
                "patient": result.get("patient"),
                "historial": result.get("historial"),
                "cita": result.get("cita"),
                "tool_name": tool_name,
            })

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.exception("WS chat error")
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass


@app.websocket("/ws/transcribe")
async def ws_transcribe_proxy(websocket: WebSocket):
    await websocket.accept()
    be1_ws_url = BE1_URL.replace("http://", "ws://").replace("https://", "wss://")
    try:
        import websockets  # type: ignore
        async with websockets.connect(f"{be1_ws_url}/ws/transcribe") as be1_ws:
            async def fwd_in():
                try:
                    while True:
                        d = await websocket.receive_text()
                        await be1_ws.send(d)
                except Exception:
                    pass

            async def fwd_out():
                try:
                    async for msg in be1_ws:
                        await websocket.send_text(msg if isinstance(msg, str) else msg.decode())
                except Exception:
                    pass

            await asyncio.gather(fwd_in(), fwd_out())
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("WS transcribe proxy error: %s", exc)
        try:
            await websocket.send_json({"type": "error", "code": "PROXY_ERROR", "message": "No se pudo conectar con BE1"})
        except Exception:
            pass
