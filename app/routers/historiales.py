import logging
import os
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.deps import get_auth_claims, require_medico
from app.core.responses import error_response, ok
from app.db.database import get_db
from app.models.db_models import Cita, Consulta, EPS, Historial, Medico, Paciente
from app.models.schemas import (
    GenerateHistorialRequest,
    GenerateHistorialResponseData,
    HistorialClinico,
    HistorialConfirmRequest,
)
from app.services.ai import AIService
from app.services.clinical_context import load_patient_clinical_context, merge_context
from app.services.clinical_enrichment import enrich_historial_for_patient
from app.services.email import send_historial_email
from app.services.frontend_serializers import apply_frontend_historial, historial_to_frontend
from app.services.pdf import PdfContext, generate_pdf

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/historiales", tags=["historiales"])
_ai = AIService()


def _normalize_sintomas(sintomas: list[str] | str) -> str:
    if isinstance(sintomas, list):
        return ", ".join(sintomas)
    return sintomas or ""


def _build_medicamentos_payload(body: HistorialConfirmRequest) -> dict:
    payload = dict(body.medicamentos or {})
    if body.alergias:
        payload["alergias"] = body.alergias
    if body.notas_adicionales:
        payload["notas_adicionales"] = body.notas_adicionales
    if body.requiere_incapacidad:
        payload["requiere_incapacidad"] = True
        if body.incapacidad_dias is not None:
            payload["incapacidad_dias"] = body.incapacidad_dias
    if body.enviar_informe_email:
        payload["enviar_informe_email"] = True
    return payload


def _paciente_owns_historial(db: Session, historial_id: int, paciente_id: int) -> bool:
    row = (
        db.query(Historial.id)
        .join(Consulta, Historial.consulta_id == Consulta.id)
        .join(Cita, Consulta.cita_id == Cita.id)
        .filter(Historial.id == historial_id, Cita.paciente_id == paciente_id)
        .first()
    )
    return row is not None


def _build_pdf_context(db: Session, consulta: Consulta) -> PdfContext:
    cita = db.query(Cita).filter(Cita.id == consulta.cita_id).first()
    if not cita:
        return PdfContext()

    medico = db.query(Medico).filter(Medico.id == cita.medico_id).first()
    paciente = db.query(Paciente).filter(Paciente.id == cita.paciente_id).first()
    eps = None
    if paciente and paciente.eps_id:
        eps = db.query(EPS).filter(EPS.id == paciente.eps_id).first()
    elif medico and medico.eps_id:
        eps = db.query(EPS).filter(EPS.id == medico.eps_id).first()

    return PdfContext(medico=medico, eps=eps)


def _apply_confirm_body(historial: Historial, body: HistorialConfirmRequest) -> None:
    historial.motivo_consulta = body.motivo_consulta
    historial.sintomas = _normalize_sintomas(body.sintomas)
    historial.diagnostico = body.diagnostico
    historial.plan_tratamiento = body.plan_tratamiento
    historial.medicamentos_sugeridos = _build_medicamentos_payload(body)
    historial.confirmado_por_medico = body.confirmado_por_medico


def _finalize_historial_pdf(
    historial: Historial,
    pdf_context: PdfContext,
    db: Session,
) -> str | None:
    try:
        pdf_path = generate_pdf(historial, context=pdf_context)
        historial.pdf_path = pdf_path
        db.commit()
        return pdf_path
    except Exception:
        logger.exception("PDF generation failed for historial %s", historial.id)
        return None


def _medico_owns_consulta(db: Session, consulta: Consulta, medico_id: int) -> bool:
    cita = db.query(Cita).filter(Cita.id == consulta.cita_id).first()
    return bool(cita and cita.medico_id == medico_id)


@router.post("")
def create_historial(
    body: HistorialConfirmRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Persist a physician-confirmed historial, generate PDF and notify patient."""
    consulta = db.query(Consulta).filter(Consulta.id == body.consulta_id).first()
    if not consulta:
        return error_response("NOT_FOUND", "Consulta no encontrada.", 404)

    auth = require_medico(request)
    if auth:
        _, medico_id = auth
        if not _medico_owns_consulta(db, consulta, medico_id):
            return error_response(
                "FORBIDDEN",
                "Solo el médico de la cita puede confirmar este historial.",
                403,
            )

    pdf_context = _build_pdf_context(db, consulta)

    existing = (
        db.query(Historial).filter(Historial.consulta_id == body.consulta_id).first()
    )
    if existing:
        _apply_confirm_body(existing, body)
        db.commit()
        db.refresh(existing)

        if not existing.pdf_path or not os.path.isfile(existing.pdf_path or ""):
            if _finalize_historial_pdf(existing, pdf_context, db) is None:
                return error_response("PDF_ERROR", "No se pudo generar el PDF.", 500)

        email_sent = False
        if body.confirmado_por_medico and body.enviar_informe_email:
            cita = db.query(Cita).filter(Cita.id == consulta.cita_id).first()
            paciente = (
                db.query(Paciente).filter(Paciente.id == cita.paciente_id).first()
                if cita
                else None
            )
            if paciente:
                email_sent = send_historial_email(
                    paciente,
                    existing,
                    requiere_incapacidad=body.requiere_incapacidad,
                    incapacidad_dias=body.incapacidad_dias,
                )

        return ok(
            {
                "historial_id": existing.id,
                "pdf_url": f"/historiales/{existing.id}/pdf",
                "email_sent": email_sent,
                "reused": True,
            }
        )

    historial = Historial(
        consulta_id=body.consulta_id,
        motivo_consulta=body.motivo_consulta,
        sintomas=_normalize_sintomas(body.sintomas),
        diagnostico=body.diagnostico,
        plan_tratamiento=body.plan_tratamiento,
        medicamentos_sugeridos=_build_medicamentos_payload(body),
        confirmado_por_medico=body.confirmado_por_medico,
    )
    db.add(historial)
    db.commit()
    db.refresh(historial)

    if _finalize_historial_pdf(historial, pdf_context, db) is None:
        return error_response("PDF_ERROR", "No se pudo generar el PDF.", 500)

    email_sent = False
    if body.confirmado_por_medico and body.enviar_informe_email:
        cita = db.query(Cita).filter(Cita.id == consulta.cita_id).first()
        paciente = (
            db.query(Paciente).filter(Paciente.id == cita.paciente_id).first()
            if cita
            else None
        )
        if paciente:
            email_sent = send_historial_email(
                paciente,
                historial,
                requiere_incapacidad=body.requiere_incapacidad,
                incapacidad_dias=body.incapacidad_dias,
            )
        elif not paciente:
            logger.warning("No se envió email: paciente no encontrado para consulta %s", body.consulta_id)

    return ok(
        {
            "historial_id": historial.id,
            "pdf_url": f"/historiales/{historial.id}/pdf",
            "email_sent": email_sent,
        }
    )


@router.get("/{id}")
def get_historial(id: int, request: Request, db: Session = Depends(get_db)):
    historial = db.query(Historial).filter(Historial.id == id).first()
    if not historial:
        return error_response("NOT_FOUND", "Historial no encontrado.", 404)

    auth = require_medico(request)
    if auth:
        _, medico_id = auth
        consulta = db.query(Consulta).filter(Consulta.id == historial.consulta_id).first()
        if consulta and not _medico_owns_consulta(db, consulta, medico_id):
            return error_response("FORBIDDEN", "No puede ver este historial.", 403)

    consulta = db.query(Consulta).filter(Consulta.id == historial.consulta_id).first()
    paciente = None
    if consulta:
        cita = db.query(Cita).filter(Cita.id == consulta.cita_id).first()
        if cita:
            paciente = db.query(Paciente).filter(Paciente.id == cita.paciente_id).first()

    return ok(historial_to_frontend(historial, paciente=paciente))


@router.put("/{id}")
def update_historial(id: int, body: dict, request: Request, db: Session = Depends(get_db)):
    historial = db.query(Historial).filter(Historial.id == id).first()
    if not historial:
        return error_response("NOT_FOUND", "Historial no encontrado.", 404)

    auth = require_medico(request)
    if not auth:
        return error_response("FORBIDDEN", "Solo médicos autenticados.", 403)
    _, medico_id = auth
    consulta = db.query(Consulta).filter(Consulta.id == historial.consulta_id).first()
    if consulta and not _medico_owns_consulta(db, consulta, medico_id):
        return error_response("FORBIDDEN", "No puede editar este historial.", 403)

    apply_frontend_historial(historial, body)
    db.commit()
    db.refresh(historial)

    paciente = None
    if consulta:
        cita = db.query(Cita).filter(Cita.id == consulta.cita_id).first()
        if cita:
            paciente = db.query(Paciente).filter(Paciente.id == cita.paciente_id).first()
    return ok(historial_to_frontend(historial, paciente=paciente))


@router.post("/{id}/firmar")
def firmar_historial(id: int, request: Request, db: Session = Depends(get_db)):
    historial = db.query(Historial).filter(Historial.id == id).first()
    if not historial:
        return error_response("NOT_FOUND", "Historial no encontrado.", 404)

    auth = require_medico(request)
    if not auth:
        return error_response("FORBIDDEN", "Solo médicos autenticados.", 403)
    _, medico_id = auth

    consulta = db.query(Consulta).filter(Consulta.id == historial.consulta_id).first()
    if consulta and not _medico_owns_consulta(db, consulta, medico_id):
        return error_response("FORBIDDEN", "No puede firmar este historial.", 403)

    historial.confirmado_por_medico = True
    pdf_context = _build_pdf_context(db, consulta) if consulta else PdfContext()
    try:
        pdf_path = generate_pdf(historial, context=pdf_context)
        historial.pdf_path = pdf_path
    except Exception:
        logger.exception("PDF generation failed for historial %s", id)
        return error_response("PDF_ERROR", "No se pudo generar el PDF.", 500)

    if consulta:
        cita = db.query(Cita).filter(Cita.id == consulta.cita_id).first()
        if cita:
            cita.estado = "terminada"
    db.commit()
    db.refresh(historial)

    paciente = None
    if consulta:
        cita = db.query(Cita).filter(Cita.id == consulta.cita_id).first()
        if cita:
            paciente = db.query(Paciente).filter(Paciente.id == cita.paciente_id).first()
    return ok(historial_to_frontend(historial, paciente=paciente))


@router.post("/{id}/enviar")
def enviar_historial(id: int, request: Request, db: Session = Depends(get_db)):
    historial = db.query(Historial).filter(Historial.id == id).first()
    if not historial:
        return error_response("NOT_FOUND", "Historial no encontrado.", 404)

    auth = require_medico(request)
    if not auth:
        return error_response("FORBIDDEN", "Solo médicos autenticados.", 403)
    _, medico_id = auth

    consulta = db.query(Consulta).filter(Consulta.id == historial.consulta_id).first()
    if consulta and not _medico_owns_consulta(db, consulta, medico_id):
        return error_response("FORBIDDEN", "No puede enviar este historial.", 403)

    historial.confirmado_por_medico = True
    if consulta:
        cita = db.query(Cita).filter(Cita.id == consulta.cita_id).first()
        paciente = (
            db.query(Paciente).filter(Paciente.id == cita.paciente_id).first()
            if cita
            else None
        )
        if paciente:
            send_historial_email(
                paciente,
                historial,
                requiere_incapacidad=bool(
                    (historial.medicamentos_sugeridos or {}).get("requiere_incapacidad")
                ),
                incapacidad_dias=(historial.medicamentos_sugeridos or {}).get("incapacidad_dias"),
            )
        if cita:
            cita.estado = "terminada"
    db.commit()
    return ok({"ok": True})


@router.get("/{id}/pdf")
def get_historial_pdf(id: int, request: Request, db: Session = Depends(get_db)):
    historial = db.query(Historial).filter(Historial.id == id).first()
    if not historial:
        return error_response("NOT_FOUND", "Historial no encontrado.", 404)

    claims = get_auth_claims(request)
    if claims and claims.get("role") == "paciente":
        if not _paciente_owns_historial(db, id, claims["subject_id"]):
            return error_response("FORBIDDEN", "No puede acceder a este historial.", 403)

    pdf_path = historial.pdf_path
    if not pdf_path or not os.path.isfile(pdf_path):
        consulta = db.query(Consulta).filter(Consulta.id == historial.consulta_id).first()
        pdf_context = _build_pdf_context(db, consulta) if consulta else PdfContext()
        try:
            pdf_path = generate_pdf(historial, context=pdf_context)
            historial.pdf_path = pdf_path
            db.commit()
        except Exception:
            logger.exception("PDF generation failed for historial %s", id)
            return error_response("PDF_ERROR", "No se pudo generar el PDF.", 500)

    if not os.path.isfile(pdf_path):
        return error_response("NOT_FOUND", "PDF no encontrado.", 404)

    return FileResponse(pdf_path, media_type="application/pdf", filename=f"historial_{id}.pdf")


@router.post("/generate")
async def generate_historial(body: GenerateHistorialRequest, db: Session = Depends(get_db)):
    """Genera historial clínico estructurado desde la transcripción de la consulta."""
    historial_id = uuid4()
    context = body.context
    paciente = None
    if body.paciente_id:
        prior_ctx, _ = load_patient_clinical_context(db, body.paciente_id)
        context = merge_context(body.context, prior_ctx)
        paciente = db.query(Paciente).filter(Paciente.id == body.paciente_id).first()
        if not paciente:
            return error_response("NOT_FOUND", "Paciente no encontrado.", 404)

    try:
        historial = await _ai.generate_historial(body.transcript, context=context)
    except ValueError:
        return error_response(
            "HISTORIAL_INVALID",
            "No se pudo generar un historial válido.",
            502,
        )
    except Exception:
        return error_response("AI_ERROR", "Error al procesar la solicitud.", 502)

    if paciente:
        historial_dict = enrich_historial_for_patient(
            db, body.paciente_id, historial.model_dump(mode="json")
        )
        historial = HistorialClinico.model_validate(historial_dict)

    payload = GenerateHistorialResponseData(
        historial_id=historial_id,
        historial=historial,
        session_id=body.session_id,
    )
    return ok(payload.model_dump(mode="json"))
