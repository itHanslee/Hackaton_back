from uuid import uuid4

from fastapi import APIRouter

from app.core.responses import error_response, ok
from app.models.schemas import GenerateHistorialRequest, GenerateHistorialResponseData
from app.services.ai import AIService

router = APIRouter(prefix="/historiales", tags=["historiales"])
_ai = AIService()


@router.post("")
async def generate_historial(body: GenerateHistorialRequest):
    """Genera historial clínico estructurado desde la transcripción de la consulta."""
    historial_id = uuid4()
    try:
        historial = await _ai.generate_historial(body.transcript, context=body.context)
        payload = GenerateHistorialResponseData(
            historial_id=historial_id,
            historial=historial,
            session_id=body.session_id,
        )
        return ok(payload.model_dump(mode="json"))
    except ValueError:
        return error_response(
            "HISTORIAL_INVALID",
            "No se pudo generar un historial válido.",
            502,
        )
    except Exception:
        return error_response("AI_ERROR", "Error al procesar la solicitud.", 502)
