import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import date

from app.core.audio import check_audio_size, decode_base64_audio
from app.core.config import Settings, get_settings
from app.models.schemas import (
    AppointmentSlots,
    HistorialClinico,
    IntentType,
    MedicamentoDisponible,
    MedicamentoIdeal,
    MedicamentosHistorial,
    NO_DEFINIDO,
)
from app.services.gemini_llm import complete_with_gemini
from app.services.gemini_stt import transcribe_with_gemini
from app.services.intents import classify_intent_rule_based, intent_reply_message, suggest_slot

logger = logging.getLogger(__name__)

HISTORIAL_JSON_SCHEMA = """
{
  "motivo_consulta": "string",
  "sintomas": ["string"],
  "diagnostico": "string",
  "plan_tratamiento": "string",
  "alergias": "string",
  "notas_adicionales": "string",
  "medicamentos": {
    "disponibles_eps": [{"nombre": "string", "dosis": "string", "frecuencia": "string"}],
    "ideales_sugeridos": [{"nombre": "string", "razon": "string"}]
  }
}
"""

APPOINTMENT_SLOTS_SCHEMA = """
{
  "fecha": "YYYY-MM-DD o null",
  "hora": "HH:MM (24h) o null",
  "especialidad": "slug en minúsculas (ej. cardiologia, pediatria) o null"
}
"""


class ServiceError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class ProcessChatResult:
    intent: IntentType
    message: str | None
    historial: HistorialClinico | None


class AIService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def validate_api_keys(self) -> None:
        if self.settings.mock_ai:
            return
        if not (self.settings.google_api_key or "").strip():
            raise ServiceError(
                "MISSING_GOOGLE_KEY",
                "GOOGLE_API_KEY es obligatoria (Gemini STT + LLM).",
            )

    def _ensure_api_keys(self) -> None:
        self.validate_api_keys()

    def _timeout_sec(self) -> float:
        return float(self.settings.api_timeout_sec)

    async def transcribe_audio_base64(self, audio_b64: str, mime_type: str) -> str:
        try:
            raw = decode_base64_audio(audio_b64)
        except ValueError as exc:
            raise ValueError(f"Audio inválido: {exc}") from exc

        check_audio_size(raw, max_mb=self.settings.max_audio_mb)

        if self.settings.mock_ai:
            return "Paciente refiere dolor de cabeza desde hace dos días, sin fiebre."

        return await self.transcribe_bytes(raw, mime_type)

    async def transcribe_bytes(self, data: bytes, mime_type: str) -> str:
        if self.settings.mock_ai:
            return "Paciente refiere dolor de cabeza desde hace dos días, sin fiebre."

        check_audio_size(data, max_mb=self.settings.max_audio_mb)
        self._ensure_api_keys()

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(transcribe_with_gemini, data, mime_type, self.settings),
                timeout=self._timeout_sec(),
            )
        except asyncio.TimeoutError as exc:
            raise ServiceError(
                "TRANSCRIBE_TIMEOUT",
                f"La transcripción Gemini superó {self._timeout_sec():.0f}s.",
            ) from exc
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

    async def process_chat(
        self,
        text: str,
        *,
        generate_historial: bool = False,
        classify_intent: bool | None = None,
        include_chat_reply: bool | None = None,
        context: dict[str, str] | None = None,
    ) -> ProcessChatResult:
        if classify_intent is None:
            classify_intent = not generate_historial
        if include_chat_reply is None:
            include_chat_reply = not generate_historial

        if generate_historial:
            intent: IntentType = "generar_historial"
        elif classify_intent:
            intent = await self.classify_intent(text)
        else:
            intent = "desconocido"

        historial: HistorialClinico | None = None
        if generate_historial or intent == "generar_historial":
            historial = await self.generate_historial(text, context=context)

        message: str | None = None
        if include_chat_reply:
            message = await self.chat_reply(text, intent)

        return ProcessChatResult(intent=intent, message=message, historial=historial)

    async def classify_intent(self, text: str) -> IntentType:
        if self.settings.mock_ai:
            return classify_intent_rule_based(text)

        self._ensure_api_keys()
        prompt = (
            "Clasifica la intención del usuario en UNA de estas etiquetas exactas: "
            "agendar_cita, consulta_medica, generar_historial, desconocido.\n"
            f"Texto: {text}\n"
            "Responde solo con la etiqueta, sin explicación."
        )
        label = (await self._llm_complete(prompt)).strip().lower()
        allowed: list[IntentType] = [
            "agendar_cita",
            "consulta_medica",
            "generar_historial",
            "desconocido",
        ]
        if label in allowed:
            return label  # type: ignore[return-value]
        return classify_intent_rule_based(text)

    async def extract_appointment_slots(self, text: str) -> AppointmentSlots:
        if self.settings.mock_ai:
            return AppointmentSlots(especialidad=suggest_slot("agendar_cita", text))

        self._ensure_api_keys()
        today = date.today().isoformat()
        prompt = f"""Extrae datos de agendamiento de cita médica del siguiente mensaje en español (Colombia).
Hoy es {today}.
Responde SOLO con JSON válido usando este esquema:
{APPOINTMENT_SLOTS_SCHEMA}

Reglas:
- fecha en formato YYYY-MM-DD si se menciona (interpreta "mañana", "el lunes", etc. relativamente a hoy).
- hora en formato HH:MM 24h si se menciona.
- especialidad como slug sin tildes (cardiologia, pediatria, medicina_general, etc.) o null.
- Usa null para campos no mencionados.

Mensaje:
{text}
"""
        raw = await self._llm_complete(prompt, json_mode=True)
        try:
            data = json.loads(_strip_json_fence(raw))
            return AppointmentSlots(
                fecha=data.get("fecha"),
                hora=data.get("hora"),
                especialidad=data.get("especialidad"),
            )
        except (json.JSONDecodeError, ValueError):
            logger.warning("Invalid appointment slots JSON, using regex fallback")
            return AppointmentSlots(especialidad=suggest_slot("agendar_cita", text))

    async def generate_historial(
        self,
        transcript: str,
        context: dict[str, str] | None = None,
    ) -> HistorialClinico:
        if self.settings.mock_ai:
            return _mock_historial_from_transcript(transcript, context)

        self._ensure_api_keys()
        prompt = _historial_prompt(transcript, context)
        raw = await self._llm_complete(prompt, json_mode=True)
        try:
            return _parse_historial_json(raw)
        except ValueError:
            logger.warning("Historial JSON inválido, reintentando una vez")
            retry_prompt = (
                prompt
                + "\n\nIMPORTANTE: Tu respuesta anterior no fue JSON válido. "
                "Responde ÚNICAMENTE con un objeto JSON que cumpla el esquema, sin markdown."
            )
            raw_retry = await self._llm_complete(retry_prompt, json_mode=True)
            return _parse_historial_json(raw_retry)

    async def chat_reply(self, text: str, intent: IntentType) -> str:
        if self.settings.mock_ai:
            return intent_reply_message(intent)

        self._ensure_api_keys()
        prompt = (
            "Eres MediNote, asistente médico en español (Colombia). "
            f"Intención detectada: {intent}. "
            f"Mensaje del usuario: {text}\n"
            "Responde en 1-2 frases, claro y profesional."
        )
        return await self._llm_complete(prompt)

    async def _llm_complete(self, user_prompt: str, *, json_mode: bool = False) -> str:
        self._ensure_api_keys()
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    complete_with_gemini,
                    user_prompt,
                    self.settings,
                    json_mode=json_mode,
                ),
                timeout=self._timeout_sec(),
            )
        except asyncio.TimeoutError as exc:
            raise ServiceError(
                "LLM_TIMEOUT",
                f"Gemini superó {self._timeout_sec():.0f}s.",
            ) from exc
        except ValueError as exc:
            raise ServiceError("GEMINI_LLM_FAILED", str(exc)) from exc


def _strip_json_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    return text


def _historial_prompt(transcript: str, context: dict[str, str] | None) -> str:
    ctx_block = ""
    if context:
        lines = "\n".join(f"- {k}: {v}" for k, v in context.items())
        ctx_block = f"\nContexto adicional:\n{lines}\n"
    return f"""Eres un asistente médico. A partir de la transcripción de una consulta en español (Colombia),
genera un historial clínico en JSON válido con este esquema exacto:
{HISTORIAL_JSON_SCHEMA}

Reglas:
- La transcripción es la fuente principal de la consulta actual (motivo, síntomas nuevos, hallazgos de hoy).
- Si el contexto clínico previo incluye alergias, medicamentos o diagnósticos relevantes,
  DEBES reflejarlos en el historial aunque el paciente no los repita en esta visita.
- El campo "alergias" debe incluir TODAS las alergias conocidas (previas + mencionadas hoy).
- NO incluyas en medicamentos.disponibles_eps ni ideales_sugeridos fármacos contraindicados
  por alergias conocidas del paciente.
- Para datos de esta consulta no mencionados y sin antecedente previo, usa el valor exacto "{NO_DEFINIDO}".
- Responde SOLO con el JSON, sin markdown ni texto adicional.
{ctx_block}
Transcripción:
{transcript}
"""


def _mock_historial_from_transcript(
    transcript: str,
    context: dict[str, str] | None = None,
) -> HistorialClinico:
    t = transcript.strip()
    lower = t.lower()
    ctx = context or {}

    sintomas: list[str] = []
    if "dolor" in lower:
        if any(w in lower for w in ("cabeza", "cefalea", "frontal")):
            sintomas.append("Cefalea")
        elif any(w in lower for w in ("pecho", "torácico", "toracico")):
            sintomas.append("Dolor torácico")
        else:
            sintomas.append("Dolor referido por el paciente")
    if "fiebre" in lower:
        sintomas.append("Fiebre")
    if "fatiga" in lower or "cansancio" in lower:
        sintomas.append("Fatiga")
    if "náusea" in lower or "nausea" in lower:
        sintomas.append("Náuseas")
    if any(w in lower for w in ("estómago", "estomago", "epigástr", "epigastr")):
        sintomas.append("Dolor epigástrico")
    if "abdominal" in lower:
        sintomas.append("Dolor abdominal")
    if not sintomas:
        sintomas = [NO_DEFINIDO]

    motivo = ctx.get("motivo") or _derive_motivo(t, lower)
    diagnostico = ctx.get("diagnostico") or _derive_diagnostico(lower, motivo)
    plan = ctx.get("plan") or (
        "Seguimiento ambulatorio; control si empeoran los síntomas."
    )

    medicamentos = MedicamentosHistorial()
    prior_alergias = ctx.get("alergias_conocidas", "")
    allergy_terms = [a.strip().lower() for a in prior_alergias.split(",") if a.strip()]

    def _safe_to_prescribe(name: str) -> bool:
        lower = name.lower()
        return not any(term in lower or lower in term for term in allergy_terms if len(term) >= 3)

    if any(w in lower for w in ("acetaminofén", "acetaminofen", "paracetamol")):
        if _safe_to_prescribe("Acetaminofén"):
            medicamentos.disponibles_eps.append(
                MedicamentoDisponible(
                    nombre="Acetaminofén",
                    dosis="500 mg",
                    frecuencia="cada 8 horas",
                )
            )
    if "ibuprofeno" in lower and _safe_to_prescribe("Ibuprofeno"):
        medicamentos.disponibles_eps.append(
            MedicamentoDisponible(
                nombre="Ibuprofeno",
                dosis="400 mg",
                frecuencia="cada 8 horas",
            )
        )

    alergias = prior_alergias if prior_alergias else NO_DEFINIDO

    return HistorialClinico(
        motivo_consulta=motivo,
        sintomas=sintomas,
        diagnostico=diagnostico,
        plan_tratamiento=plan,
        alergias=alergias,
        notas_adicionales=NO_DEFINIDO,
        medicamentos=medicamentos,
    )


def _derive_motivo(transcript: str, lower: str) -> str:
    if "dolor de cabeza" in lower or "cefalea" in lower:
        return "Cefalea"
    if "dolor de pecho" in lower or "dolor torácico" in lower:
        return "Dolor torácico"
    if "estómago" in lower or "estomago" in lower or "epigástr" in lower or "epigastr" in lower:
        return "Dolor abdominal"
    if "tos" in lower:
        return "Tos"
    if "fiebre" in lower:
        return "Síndrome febril"
    if "abdominal" in lower:
        return "Dolor abdominal"
    first = transcript.split(".")[0].strip()
    if len(first) > 120:
        first = first[:117] + "..."
    return first or NO_DEFINIDO


def _derive_diagnostico(lower: str, motivo: str) -> str:
    if "gastritis" in lower:
        return "Gastritis"
    if any(w in lower for w in ("estómago", "estomago", "epigástr", "epigastr")):
        return "Gastritis — impresión clínica"
    if "cefalea" in lower or "dolor de cabeza" in lower:
        return "Cefalea tensional (R51) — impresión clínica"
    if "fiebre" in lower and "sin fiebre" not in lower:
        return "Proceso febril — estudio pendiente"
    if "dolor de pecho" in lower:
        return "Dolor torácico atípico — valoración clínica"
    return f"Impresión diagnóstica acorde a: {motivo}"


def _normalize_historial_data(data: dict) -> dict:
    normalized = dict(data)

    if "motivo_consulta" not in normalized and "motivo" in normalized:
        normalized["motivo_consulta"] = normalized.pop("motivo")
    if "plan_tratamiento" not in normalized and "plan" in normalized:
        normalized["plan_tratamiento"] = normalized.pop("plan")

    meds = normalized.get("medicamentos")
    if isinstance(meds, list):
        normalized["medicamentos"] = {
            "disponibles_eps": meds,
            "ideales_sugeridos": [],
        }
    elif not isinstance(meds, dict):
        normalized["medicamentos"] = {
            "disponibles_eps": [],
            "ideales_sugeridos": [],
        }
    else:
        for key in ("disponibles_eps", "ideales_sugeridos"):
            val = meds.get(key)
            if val is None or val == NO_DEFINIDO or isinstance(val, str):
                meds[key] = []
            elif not isinstance(val, list):
                meds[key] = []
        normalized["medicamentos"] = meds

    string_fields = [
        "motivo_consulta",
        "diagnostico",
        "plan_tratamiento",
        "alergias",
        "notas_adicionales",
    ]
    for field in string_fields:
        value = normalized.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            normalized[field] = NO_DEFINIDO

    if not normalized.get("sintomas"):
        normalized["sintomas"] = [NO_DEFINIDO]

    if "medicamentos" not in normalized or normalized["medicamentos"] is None:
        normalized["medicamentos"] = {
            "disponibles_eps": [],
            "ideales_sugeridos": [],
        }

    return normalized


def _parse_historial_json(raw: str) -> HistorialClinico:
    text = _strip_json_fence(raw)
    try:
        data = json.loads(text)
        data = _normalize_historial_data(data)
        return HistorialClinico.model_validate(data)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Invalid historial JSON from LLM: %s", exc)
        raise ValueError("El modelo no devolvió un historial JSON válido") from exc
