import logging
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import get_auth_claims
from app.core.responses import error_response, ok
from app.db.database import get_db
from app.models.db_models import Cita, Consulta, Historial, Paciente
from app.services.ai import AIService, ServiceError
from app.services.clinical_context import build_prior_context, fetch_prior_historiales
from app.services.clinical_enrichment import enrich_historial_for_patient
from app.services.frontend_serializers import cita_to_activa

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/consultas", tags=["consultas"])
_ai = AIService()


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


def _normalize_sintomas(sintomas: list[str] | str) -> str:
    if isinstance(sintomas, list):
        return ", ".join(sintomas)
    return sintomas or ""


def _persist_historial_from_dict(db: Session, consulta_id: int, historial_dict: dict) -> Historial:
    existing = db.query(Historial).filter(Historial.consulta_id == consulta_id).first()
    if existing:
        existing.motivo_consulta = historial_dict.get("motivo_consulta", "")
        existing.sintomas = _normalize_sintomas(historial_dict.get("sintomas", []))
        existing.diagnostico = historial_dict.get("diagnostico", "")
        existing.plan_tratamiento = historial_dict.get("plan_tratamiento", "")
        existing.medicamentos_sugeridos = historial_dict.get("medicamentos", {})
        db.commit()
        db.refresh(existing)
        return existing

    historial = Historial(
        consulta_id=consulta_id,
        motivo_consulta=historial_dict.get("motivo_consulta", ""),
        sintomas=_normalize_sintomas(historial_dict.get("sintomas", [])),
        diagnostico=historial_dict.get("diagnostico", ""),
        plan_tratamiento=historial_dict.get("plan_tratamiento", ""),
        medicamentos_sugeridos=historial_dict.get("medicamentos", {}),
        confirmado_por_medico=False,
    )
    db.add(historial)
    db.commit()
    db.refresh(historial)
    return historial


@router.get("/activa")
def get_consulta_activa(request: Request, db: Session = Depends(get_db)):
    claims = get_auth_claims(request)
    if not claims or claims.get("role") != "medico":
        return error_response("FORBIDDEN", "Solo médicos autenticados.", 403)

    medico_id = claims["subject_id"]
    cita = (
        db.query(Cita)
        .filter(Cita.medico_id == medico_id, Cita.estado == "activa")
        .order_by(Cita.fecha_hora.desc())
        .first()
    )
    if not cita:
        cita = (
            db.query(Cita)
            .filter(Cita.medico_id == medico_id, Cita.estado.in_(["pendiente", "programada"]))
            .order_by(Cita.fecha_hora.asc())
            .first()
        )
    if not cita:
        return error_response("NOT_FOUND", "No hay consulta activa.", 404)

    return ok(cita_to_activa(db, cita))


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
        prior_historiales = fetch_prior_historiales(db, paciente_id)
        context = build_prior_context(prior_historiales)
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

        historial_dict = enrich_historial_for_patient(
            db, paciente_id, historial_clinico.model_dump(mode="json")
        )
        historial_row = _persist_historial_from_dict(db, existing_consulta.id, historial_dict)
        return ok(
            {
                "consulta_id": existing_consulta.id,
                "historial_id": historial_row.id,
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

    prior_historiales = fetch_prior_historiales(db, paciente_id)
    context = build_prior_context(prior_historiales)

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

    historial_dict = enrich_historial_for_patient(
        db, paciente_id, historial_clinico.model_dump(mode="json")
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

    historial_row = _persist_historial_from_dict(db, consulta.id, historial_dict)

    return ok(
        {
            "consulta_id": consulta.id,
            "historial_id": historial_row.id,
            "transcripcion": transcripcion,
            "historial": historial_dict,
        }
    )
