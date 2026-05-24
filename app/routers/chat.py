from fastapi import APIRouter

from app.core.responses import error_response, ok
from app.models.schemas import ChatRequest, ChatResponseData
from app.services.ai import AIService, ServiceError
from app.services.intents import intent_reply_message

router = APIRouter(prefix="/chat", tags=["chat"])
_ai = AIService()


@router.post("")
async def chat(body: ChatRequest):
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

    try:
        result = await _ai.process_chat(text, generate_historial=body.generate_historial)
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
        historial=result.historial,
    )
    return ok(payload.model_dump(mode="json"))
