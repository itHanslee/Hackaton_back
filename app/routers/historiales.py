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
from app.services.clinical_context import (
    apply_prior_clinical_safety,
    load_patient_clinical_context,
    merge_context,
)
from app.services.email import send_historial_email
from app.services.medicamentos import MedicamentosService
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
        pdf_url = f"/historiales/{existing.id}/pdf"
        if not existing.pdf_path or not os.path.isfile(existing.pdf_path or ""):
            try:
                pdf_path = generate_pdf(existing, context=pdf_context)
                existing.pdf_path = pdf_path
                db.commit()
            except Exception:
                logger.exception("PDF regeneration failed for historial %s", existing.id)
        return ok(
            {
                "historial_id": existing.id,
                "pdf_url": pdf_url,
                "email_sent": False,
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

    try:
        pdf_path = generate_pdf(historial, context=pdf_context)
        historial.pdf_path = pdf_path
        db.commit()
    except Exception:
        logger.exception("PDF generation failed for historial %s", historial.id)
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
    prior_rows: list[Historial] = []
    paciente = None
    if body.paciente_id:
        prior_ctx, prior_rows = load_patient_clinical_context(db, body.paciente_id)
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

    if paciente and prior_rows:
        historial_dict = historial.model_dump(mode="json")
        allergy_terms = apply_prior_clinical_safety(historial_dict, prior_rows)
        historial_dict = MedicamentosService().enrich_historial(
            db, paciente.eps_id, historial_dict, allergy_terms=allergy_terms
        )
        historial = HistorialClinico.model_validate(historial_dict)

    payload = GenerateHistorialResponseData(
        historial_id=historial_id,
        historial=historial,
        session_id=body.session_id,
    )
    return ok(payload.model_dump(mode="json"))
