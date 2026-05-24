"""Orquestación async del pipeline OCR → RETHUS → ADRES → reporte."""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.db_models import IncapacidadRadicacionJob
from app.services.historial_bundle import load_historial_bundle
from app.services.incapacidad_pdf import (
    build_incapacidad_data,
    generate_incapacidad_pdf,
    incapacidad_data_as_ocr_fallback,
)
from app.services.radicado_client import RadicadoServiceError, ocr_pdf, validar_adres, validar_rethus
from app.services.radicado_report import build_validation_report

logger = logging.getLogger(__name__)


def _normalize_ocr(raw: dict[str, Any]) -> dict[str, Any]:
    extracted = raw.get("extracted_data")
    if isinstance(extracted, dict):
        return extracted
    return raw


def _merge_ocr(extracted: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    merged = dict(fallback)
    for key, value in extracted.items():
        if value not in (None, "", []):
            merged[key] = value
    return merged


def _update_job(db: Session, job: IncapacidadRadicacionJob, **fields) -> None:
    for key, value in fields.items():
        setattr(job, key, value)
    job.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(job)


def job_to_dict(job: IncapacidadRadicacionJob) -> dict[str, Any]:
    return {
        "job_id": job.id,
        "historial_id": job.historial_id,
        "medico_id": job.medico_id,
        "estado": job.estado,
        "paso_actual": job.paso_actual,
        "pdf_path": job.pdf_path,
        "score": job.score,
        "recomendacion": job.recomendacion,
        "error": job.error_message,
        "pasos": {
            "ocr": job.ocr_json,
            "rethus": job.rethus_json,
            "adres": job.adres_json,
            "reporte": job.reporte_json,
        },
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


def ensure_incapacidad_pdf(db: Session, historial_id: int, dias_override: int | None = None) -> tuple[str, dict]:
    bundle = load_historial_bundle(db, historial_id)
    if not bundle:
        raise ValueError("Historial no encontrado")
    pdf_path, data = generate_incapacidad_pdf(bundle, dias_override=dias_override)
    bundle.historial.incapacidad_pdf_path = pdf_path
    db.commit()
    return pdf_path, incapacidad_data_as_ocr_fallback(data)


def run_pipeline(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.query(IncapacidadRadicacionJob).filter(IncapacidadRadicacionJob.id == job_id).first()
        if not job:
            return

        bundle = load_historial_bundle(db, job.historial_id)
        if not bundle:
            _update_job(db, job, estado="error", error_message="Historial no encontrado")
            return

        pdf_path = job.pdf_path or bundle.historial.incapacidad_pdf_path
        if not pdf_path or not os.path.isfile(pdf_path):
            pdf_path, _ = ensure_incapacidad_pdf(db, job.historial_id)
            job.pdf_path = pdf_path

        fallback = incapacidad_data_as_ocr_fallback(build_incapacidad_data(bundle))
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()

        _update_job(db, job, estado="ocr", paso_actual=1, pdf_path=pdf_path, error_message=None)
        try:
            ocr_raw = ocr_pdf(pdf_bytes, filename=os.path.basename(pdf_path))
        except RadicadoServiceError as exc:
            logger.warning("OCR remoto falló, usando datos BD: %s", exc)
            ocr_raw = {"extracted_data": fallback, "source": "database_fallback"}
        ocr_data = _merge_ocr(_normalize_ocr(ocr_raw), fallback)
        _update_job(db, job, ocr_json=ocr_data, estado="rethus", paso_actual=2)

        rethus_payload = {
            "registro_medico": ocr_data.get("registro_medico") or fallback.get("registro_medico"),
            "medico_nombre": ocr_data.get("medico_nombre") or fallback.get("medico_nombre"),
            "tipo_documento": ocr_data.get("paciente_tipo_documento") or "CC",
            "numero_documento": ocr_data.get("registro_medico") or fallback.get("registro_medico"),
        }
        rethus_data = validar_rethus(rethus_payload)
        _update_job(db, job, rethus_json=rethus_data, estado="adres", paso_actual=3)

        adres_data = validar_adres(
            tipo_documento=str(ocr_data.get("paciente_tipo_documento") or "CC"),
            numero_documento=str(ocr_data.get("paciente_numero_documento") or ""),
            eps_laravel=str(ocr_data.get("eps_detectada") or fallback.get("eps_detectada") or ""),
        )
        _update_job(db, job, adres_json=adres_data, estado="reporte", paso_actual=4)

        reporte = build_validation_report(ocr_data, rethus_data, adres_data)
        _update_job(
            db,
            job,
            reporte_json=reporte,
            score=reporte.get("score_global"),
            recomendacion=reporte.get("recomendacion"),
            estado="completo",
            paso_actual=4,
        )
    except Exception as exc:
        logger.exception("Pipeline radicado falló job=%s", job_id)
        job = db.query(IncapacidadRadicacionJob).filter(IncapacidadRadicacionJob.id == job_id).first()
        if job:
            _update_job(db, job, estado="error", error_message=str(exc))
    finally:
        db.close()


def start_radicacion_job(db: Session, historial_id: int, medico_id: int) -> IncapacidadRadicacionJob:
    bundle = load_historial_bundle(db, historial_id)
    if not bundle:
        raise ValueError("Historial no encontrado")

    pdf_path = bundle.historial.incapacidad_pdf_path
    if not pdf_path or not os.path.isfile(pdf_path):
        pdf_path, _ = ensure_incapacidad_pdf(db, historial_id)

    job = IncapacidadRadicacionJob(
        historial_id=historial_id,
        medico_id=medico_id,
        pdf_path=pdf_path,
        estado="pendiente",
        paso_actual=0,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    thread = threading.Thread(target=run_pipeline, args=(job.id,), daemon=True)
    thread.start()
    return job
