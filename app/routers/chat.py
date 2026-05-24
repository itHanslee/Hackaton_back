from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.responses import error_response, ok
from app.db.database import get_db
from app.models.db_models import Paciente
from app.models.schemas import ChatRequest, ChatResponseData, HistorialClinico
from app.services.ai import AIService, ServiceError
from app.services.clinical_context import (
    apply_prior_clinical_safety,
    load_patient_clinical_context,
    merge_context,
)
from app.services.intents import intent_reply_message
from app.services.medicamentos import MedicamentosService

router = APIRouter(prefix="/chat", tags=["chat"])
_ai = AIService()


def _resolve_context(db: Session, paciente_id: int | None, explicit: dict | None):
    if not paciente_id:
        return explicit, [], None
    prior_ctx, prior_rows = load_patient_clinical_context(db, paciente_id)
    return merge_context(explicit, prior_ctx), prior_rows, paciente_id


@router.post("")
async def chat(body: ChatRequest, db: Session = Depends(get_db)):
    """
    Recibe texto o audio (base64). Devuelve intención, slots de cita (fecha/hora/especialidad) y mensaje.
    Con generate_historial=true incluye el JSON clínico en la respuesta.
    """
    text = body.text or ""
    transcript: str | None = None

    if body.audio:
        try:
            transcript = await _ai.transcribe_audio_base64(body.audio, body.mime_type)
            text = transcript
        except ValueError:
            return error_response("INVALID_AUDIO", "Audio inválido o demasiado grande.", 400)
        except ServiceError as exc:
            return error_response(exc.code, exc.message, 502)
        except Exception:
            return error_response("TRANSCRIBE_FAILED", "No se pudo transcribir el audio.", 502)

    context, prior_rows, paciente_id = _resolve_context(db, body.paciente_id, None)

    try:
        result = await _ai.process_chat(
            text,
            generate_historial=body.generate_historial,
            context=context or None,
        )
    except ValueError:
        return error_response(
            "HISTORIAL_INVALID",
            "No se pudo generar un historial válido.",
            502,
        )
    except ServiceError as exc:
        return error_response(exc.code, exc.message, 502)
    except Exception:
        return error_response("CHAT_FAILED", "Error al procesar el mensaje.", 502)

    historial = result.historial
    if historial and paciente_id and prior_rows:
        paciente = db.query(Paciente).filter(Paciente.id == paciente_id).first()
        if paciente:
            historial_dict = historial.model_dump(mode="json")
            allergy_terms = apply_prior_clinical_safety(historial_dict, prior_rows)
            historial_dict = MedicamentosService().enrich_historial(
                db, paciente.eps_id, historial_dict, allergy_terms=allergy_terms
            )
            historial = HistorialClinico.model_validate(historial_dict)

    message = result.message or intent_reply_message(result.intent)

    appointment_slots = None
    slot_suggested = None
    if result.intent == "agendar_cita":
        appointment_slots = await _ai.extract_appointment_slots(text)
        slot_suggested = appointment_slots.especialidad

    payload = ChatResponseData(
        message=message,
        detected_intent=result.intent,
        slot_suggested=slot_suggested,
        appointment_slots=appointment_slots,
        transcript=transcript,
        historial=historial,
    )
    return ok(payload.model_dump(mode="json"))
