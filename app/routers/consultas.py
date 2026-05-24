import logging
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.responses import error_response, ok
from app.db.database import get_db
from app.models.db_models import Cita, Consulta, Historial, Paciente
from app.services.ai import AIService, ServiceError
from app.services.medicamentos import MedicamentosService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/consultas", tags=["consultas"])
_ai = AIService()


def _build_context(prior_historiales: list[Historial]) -> dict[str, str]:
    if not prior_historiales:
        return {}

    context: dict[str, str] = {}
    summaries: list[str] = []
    for h in prior_historiales[:5]:
        date_str = h.created_at.strftime("%Y-%m-%d") if h.created_at else "N/A"
        summaries.append(f"{date_str}: {h.diagnostico or 'Sin diagnóstico'}")
    context["historial_previo"] = "; ".join(summaries)

    latest = prior_historiales[0]
    if latest.diagnostico:
        context["diagnostico_previo"] = latest.diagnostico
    if latest.motivo_consulta:
        context["motivo_previo"] = latest.motivo_consulta
    return context


def _save_audio(audio_bytes: bytes, mime_type: str) -> str:
    settings = get_settings()
    audio_dir = Path(settings.audio_output_dir)
    audio_dir.mkdir(parents=True, exist_ok=True)

    ext_map = {
        "audio/webm": ".webm",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a",
        "audio/ogg": ".ogg",
    }
    ext = ext_map.get((mime_type or "").lower(), ".webm")
    filename = f"consulta_{uuid.uuid4().hex}{ext}"
    path = audio_dir / filename
    path.write_bytes(audio_bytes)
    return str(path.resolve())


@router.post("/procesar")
async def procesar_consulta(
    paciente_id: int = Form(...),
    cita_id: int = Form(...),
    audio: UploadFile | None = File(None),
    transcript: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """Transcribe consultation audio (or use provided transcript), generate historial, persist Consulta."""
    paciente = db.query(Paciente).filter(Paciente.id == paciente_id).first()
    if not paciente:
        return error_response("NOT_FOUND", "Paciente no encontrado.", 404)

    cita = db.query(Cita).filter(Cita.id == cita_id).first()
    if not cita:
        return error_response("NOT_FOUND", "Cita no encontrada.", 404)
    if cita.paciente_id != paciente_id:
        return error_response(
            "INVALID_CITA",
            "La cita no corresponde al paciente indicado.",
            400,
        )

    existing_consulta = (
        db.query(Consulta).filter(Consulta.cita_id == cita_id).order_by(Consulta.id.desc()).first()
    )
    if existing_consulta:
        prior_historiales = (
            db.query(Historial)
            .join(Consulta, Historial.consulta_id == Consulta.id)
            .join(Cita, Consulta.cita_id == Cita.id)
            .filter(Cita.paciente_id == paciente_id)
            .order_by(Historial.created_at.desc())
            .all()
        )
        context = _build_context(prior_historiales)
        try:
            historial_clinico = await _ai.generate_historial(
                existing_consulta.transcripcion, context=context
            )
        except ValueError:
            return error_response(
                "HISTORIAL_INVALID",
                "No se pudo regenerar el historial de la consulta existente.",
                502,
            )
        except ServiceError as exc:
            return error_response(exc.code, exc.message, 502)
        except Exception:
            logger.exception("Historial regeneration failed for existing consulta %s", existing_consulta.id)
            return error_response("AI_ERROR", "Error al regenerar el historial.", 502)

        historial_dict = historial_clinico.model_dump(mode="json")
        historial_dict = MedicamentosService().enrich_historial(
            db, paciente.eps_id, historial_dict
        )
        return ok(
            {
                "consulta_id": existing_consulta.id,
                "transcripcion": existing_consulta.transcripcion,
                "historial": historial_dict,
                "reused": True,
            }
        )

    audio_bytes: bytes | None = None
    mime_type = "audio/webm"
    transcripcion = (transcript or "").strip()

    if audio is not None:
        audio_bytes = await audio.read()
        mime_type = audio.content_type or "audio/webm"

    if not transcripcion:
        if not audio_bytes:
            return error_response(
                "VALIDATION_ERROR",
                "Envíe 'audio' o 'transcript'.",
                400,
            )
        try:
            transcripcion = await _ai.transcribe_bytes(audio_bytes, mime_type)
        except ValueError as exc:
            msg = str(exc)
            lower = msg.lower()
            if "google_api_key" in lower or "google-genai" in lower:
                code = "MISSING_GEMINI_CONFIG"
            elif "gemini" in lower:
                code = "GEMINI_TRANSCRIBE_FAILED"
            else:
                code = "INVALID_AUDIO"
            return error_response(code, msg, 400)
        except ServiceError as exc:
            return error_response(exc.code, exc.message, 502)
        except Exception:
            logger.exception("Transcription failed")
            return error_response("TRANSCRIBE_FAILED", "No se pudo transcribir el audio.", 502)

    prior_historiales = (
        db.query(Historial)
        .join(Consulta, Historial.consulta_id == Consulta.id)
        .join(Cita, Consulta.cita_id == Cita.id)
        .filter(Cita.paciente_id == paciente_id)
        .order_by(Historial.created_at.desc())
        .all()
    )
    context = _build_context(prior_historiales)

    try:
        historial_clinico = await _ai.generate_historial(transcripcion, context=context)
    except ValueError:
        return error_response(
            "HISTORIAL_INVALID",
            "No se pudo generar un historial válido.",
            502,
        )
    except ServiceError as exc:
        return error_response(exc.code, exc.message, 502)
    except Exception:
        logger.exception("Historial generation failed")
        return error_response("AI_ERROR", "Error al generar el historial.", 502)

    historial_dict = historial_clinico.model_dump(mode="json")
    historial_dict = MedicamentosService().enrich_historial(
        db, paciente.eps_id, historial_dict
    )

    audio_path = "text-only"
    if audio_bytes:
        try:
            audio_path = _save_audio(audio_bytes, mime_type)
        except OSError:
            logger.exception("Failed to save audio")
            return error_response("STORAGE_ERROR", "No se pudo guardar el audio.", 500)

    consulta = Consulta(
        cita_id=cita_id,
        audio_path=audio_path,
        transcripcion=transcripcion,
    )
    db.add(consulta)
    cita.estado = "activa"
    db.commit()
    db.refresh(consulta)

    return ok(
        {
            "consulta_id": consulta.id,
            "transcripcion": transcripcion,
            "historial": historial_dict,
        }
    )
