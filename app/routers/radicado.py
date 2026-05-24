"""API de radicación de incapacidades (proxy al microservicio remoto)."""

import os

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.deps import require_medico
from app.core.responses import error_response, ok
from app.db.database import get_db
from app.models.db_models import IncapacidadRadicacionJob
from app.services.historial_bundle import load_historial_bundle, medico_owns_historial
from app.services.incapacidad_pdf import build_incapacidad_data, incapacidad_data_as_ocr_fallback
from app.services.radicado_pipeline import ensure_incapacidad_pdf, job_to_dict, start_radicacion_job

router = APIRouter(prefix="/radicado", tags=["radicado"])


class IniciarRadicacionRequest(BaseModel):
    historial_id: int = Field(..., ge=1)


class GenerarDocumentoRequest(BaseModel):
    incapacidad_dias: int | None = Field(default=None, ge=1, le=365)


@router.post("/incapacidades")
def iniciar_radicacion(body: IniciarRadicacionRequest, request: Request, db: Session = Depends(get_db)):
    auth = require_medico(request)
    if not auth:
        return error_response("FORBIDDEN", "Solo médicos autenticados.", 403)
    _, medico_id = auth

    bundle = load_historial_bundle(db, body.historial_id)
    if not bundle:
        return error_response("NOT_FOUND", "Historial no encontrado.", 404)
    if not medico_owns_historial(db, bundle, medico_id):
        return error_response("FORBIDDEN", "No puede radicar este historial.", 403)

    meds = bundle.historial.medicamentos_sugeridos or {}
    if isinstance(meds, dict) and not (meds.get("requiere_incapacidad") or meds.get("incapacidad_dias")):
        return error_response("VALIDATION_ERROR", "El historial no está marcado con incapacidad.", 422)

    try:
        job = start_radicacion_job(db, body.historial_id, medico_id)
    except ValueError as exc:
        return error_response("NOT_FOUND", str(exc), 404)
    except Exception as exc:
        return error_response("RADICADO_ERROR", str(exc), 502)

    return ok(job_to_dict(job))


@router.get("/incapacidades/{job_id}")
def obtener_job(job_id: str, request: Request, db: Session = Depends(get_db)):
    auth = require_medico(request)
    if not auth:
        return error_response("FORBIDDEN", "Solo médicos autenticados.", 403)
    _, medico_id = auth

    job = db.query(IncapacidadRadicacionJob).filter(IncapacidadRadicacionJob.id == job_id).first()
    if not job:
        return error_response("NOT_FOUND", "Job no encontrado.", 404)
    if job.medico_id != medico_id:
        return error_response("FORBIDDEN", "No puede ver este job.", 403)
    return ok(job_to_dict(job))


@router.get("/historial/{historial_id}")
def obtener_job_por_historial(historial_id: int, request: Request, db: Session = Depends(get_db)):
    auth = require_medico(request)
    if not auth:
        return error_response("FORBIDDEN", "Solo médicos autenticados.", 403)
    _, medico_id = auth

    job = (
        db.query(IncapacidadRadicacionJob)
        .filter(
            IncapacidadRadicacionJob.historial_id == historial_id,
            IncapacidadRadicacionJob.medico_id == medico_id,
        )
        .order_by(IncapacidadRadicacionJob.created_at.desc())
        .first()
    )
    if not job:
        return error_response("NOT_FOUND", "Sin radicación para este historial.", 404)
    return ok(job_to_dict(job))


@router.post("/historiales/{historial_id}/documento")
def generar_documento_incapacidad(
    historial_id: int,
    body: GenerarDocumentoRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    auth = require_medico(request)
    if not auth:
        return error_response("FORBIDDEN", "Solo médicos autenticados.", 403)
    _, medico_id = auth

    bundle = load_historial_bundle(db, historial_id)
    if not bundle:
        return error_response("NOT_FOUND", "Historial no encontrado.", 404)
    if not medico_owns_historial(db, bundle, medico_id):
        return error_response("FORBIDDEN", "No puede generar documento para este historial.", 403)

    if body.incapacidad_dias is not None:
        meds = dict(bundle.historial.medicamentos_sugeridos or {})
        meds["requiere_incapacidad"] = True
        meds["incapacidad_dias"] = body.incapacidad_dias
        bundle.historial.medicamentos_sugeridos = meds
        db.commit()

    try:
        pdf_path, _ = ensure_incapacidad_pdf(db, historial_id, dias_override=body.incapacidad_dias)
    except Exception as exc:
        return error_response("PDF_ERROR", f"No se pudo generar el documento: {exc}", 500)

    data = build_incapacidad_data(bundle, dias_override=body.incapacidad_dias)
    return ok({
        "historial_id": historial_id,
        "pdf_url": f"/radicado/historiales/{historial_id}/documento/pdf",
        "metadata": incapacidad_data_as_ocr_fallback(data),
    })


@router.get("/historiales/{historial_id}/documento/pdf")
def descargar_documento_incapacidad(historial_id: int, request: Request, db: Session = Depends(get_db)):
    auth = require_medico(request)
    if not auth:
        return error_response("FORBIDDEN", "Solo médicos autenticados.", 403)
    _, medico_id = auth

    bundle = load_historial_bundle(db, historial_id)
    if not bundle:
        return error_response("NOT_FOUND", "Historial no encontrado.", 404)
    if not medico_owns_historial(db, bundle, medico_id):
        return error_response("FORBIDDEN", "No puede acceder a este documento.", 403)

    pdf_path = bundle.historial.incapacidad_pdf_path
    if not pdf_path or not os.path.isfile(pdf_path):
        return error_response("NOT_FOUND", "Genere el documento de incapacidad primero.", 404)

    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=f"incapacidad_{historial_id}.pdf",
    )
