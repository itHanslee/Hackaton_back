"""Contexto clínico previo del paciente para generación segura de historiales."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from app.models.db_models import Cita, Consulta, Historial
from app.models.schemas import NO_DEFINIDO

_MAX_VISITS_SUMMARY = 5


def fetch_prior_historiales(db: Session, paciente_id: int) -> list[Historial]:
    return (
        db.query(Historial)
        .join(Consulta, Historial.consulta_id == Consulta.id)
        .join(Cita, Consulta.cita_id == Cita.id)
        .filter(Cita.paciente_id == paciente_id)
        .order_by(Historial.created_at.desc())
        .all()
    )


def _extract_alergias_from_meds(meds: Any) -> str | None:
    if not isinstance(meds, dict):
        return None
    alergias = meds.get("alergias")
    if isinstance(alergias, str):
        text = alergias.strip()
        if text and text != NO_DEFINIDO:
            return text
    return None


def _extract_alergias_from_historial(historial: Historial) -> str | None:
    return _extract_alergias_from_meds(historial.medicamentos_sugeridos)


def _medication_names_from_historial(historial: Historial) -> list[str]:
    meds = historial.medicamentos_sugeridos
    if not isinstance(meds, dict):
        return []
    names: list[str] = []
    for key in ("disponibles_eps", "ideales_sugeridos"):
        items = meds.get(key) or []
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict):
                name = item.get("nombre") or item.get("nombre_generico") or item.get("nombre_comercial")
                if isinstance(name, str) and name.strip():
                    names.append(name.strip())
            elif isinstance(item, str) and item.strip():
                names.append(item.strip())
    return names


def parse_allergy_terms(alergias: str | None) -> list[str]:
    if not alergias or alergias.strip() == NO_DEFINIDO:
        return []
    parts = re.split(r"[,;/\n]+", alergias)
    terms: list[str] = []
    seen: set[str] = set()
    for part in parts:
        token = part.strip().lower()
        if len(token) >= 3 and token not in seen:
            seen.add(token)
            terms.append(token)
    return terms


def collect_known_allergies(historiales: list[Historial]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for h in historiales:
        raw = _extract_alergias_from_historial(h)
        for term in parse_allergy_terms(raw):
            if term not in seen:
                seen.add(term)
                merged.append(term)
    return merged


def medication_conflicts_allergy(med_name: str, allergy_terms: list[str]) -> bool:
    if not allergy_terms:
        return False
    name = med_name.lower()
    return any(term in name or name in term for term in allergy_terms)


def build_prior_context(prior_historiales: list[Historial]) -> dict[str, str]:
    if not prior_historiales:
        return {}

    context: dict[str, str] = {}
    summaries: list[str] = []
    for h in prior_historiales[:_MAX_VISITS_SUMMARY]:
        date_str = h.created_at.strftime("%Y-%m-%d") if h.created_at else "N/A"
        diag = h.diagnostico or "Sin diagnóstico"
        summaries.append(f"{date_str}: {diag}")
    context["historial_previo"] = "; ".join(summaries)

    latest = prior_historiales[0]
    if latest.diagnostico:
        context["diagnostico_previo"] = latest.diagnostico
    if latest.motivo_consulta:
        context["motivo_previo"] = latest.motivo_consulta
    if latest.plan_tratamiento and latest.plan_tratamiento.strip() != NO_DEFINIDO:
        context["plan_tratamiento_previo"] = latest.plan_tratamiento

    med_names = _medication_names_from_historial(latest)
    if med_names:
        context["medicamentos_previos"] = ", ".join(med_names[:8])

    allergy_terms = collect_known_allergies(prior_historiales)
    if allergy_terms:
        context["alergias_conocidas"] = ", ".join(allergy_terms)
        context["advertencia_seguridad"] = (
            "NO prescribir ni sugerir medicamentos que contengan o estén relacionados "
            f"con estas alergias: {context['alergias_conocidas']}."
        )

    return context


def merge_context(
    explicit: dict[str, str] | None,
    prior: dict[str, str],
) -> dict[str, str]:
    merged = dict(prior)
    if explicit:
        merged.update(explicit)
    return merged


def load_patient_clinical_context(
    db: Session, paciente_id: int
) -> tuple[dict[str, str], list[Historial]]:
    prior = fetch_prior_historiales(db, paciente_id)
    return build_prior_context(prior), prior


def apply_prior_clinical_safety(
    historial_dict: dict[str, Any],
    prior_historiales: list[Historial],
) -> list[str]:
    """Fusiona alergias conocidas en el historial generado. Devuelve términos para filtrar meds."""
    allergy_terms = collect_known_allergies(prior_historiales)
    if not allergy_terms:
        return []

    known_label = ", ".join(t.title() for t in allergy_terms)
    current = historial_dict.get("alergias")
    if not current or str(current).strip() == NO_DEFINIDO:
        historial_dict["alergias"] = known_label
    else:
        existing = parse_allergy_terms(str(current))
        combined = existing + [t for t in allergy_terms if t not in existing]
        historial_dict["alergias"] = ", ".join(t.title() for t in combined)

    return allergy_terms
