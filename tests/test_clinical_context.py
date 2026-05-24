from datetime import datetime

from app.models.db_models import Historial
from app.services.clinical_context import (
    apply_prior_clinical_safety,
    build_prior_context,
    collect_known_allergies,
    medication_conflicts_allergy,
    parse_allergy_terms,
)
from app.services.medicamentos import MedicamentosService


def _make_historial(*, consulta_id: int, alergias: str | None = None) -> Historial:
    payload = {}
    if alergias:
        payload["alergias"] = alergias
    return Historial(
        id=consulta_id,
        consulta_id=consulta_id,
        motivo_consulta="Control",
        sintomas="Dolor",
        diagnostico="Cefalea",
        plan_tratamiento="Reposo",
        medicamentos_sugeridos=payload,
        confirmado_por_medico=True,
        created_at=datetime.utcnow(),
    )


def test_parse_allergy_terms_splits_and_dedupes():
    terms = parse_allergy_terms("Ibuprofeno, penicilina; Ibuprofeno")
    assert terms == ["ibuprofeno", "penicilina"]


def test_build_prior_context_includes_allergies_and_warning():
    rows = [_make_historial(consulta_id=1, alergias="Ibuprofeno, Aspirina")]
    ctx = build_prior_context(rows)
    assert "ibuprofeno" in ctx["alergias_conocidas"]
    assert "aspirina" in ctx["alergias_conocidas"]
    assert "advertencia_seguridad" in ctx


def test_apply_prior_clinical_safety_merges_allergies():
    rows = [_make_historial(consulta_id=1, alergias="Ibuprofeno")]
    historial = {"alergias": "No definido", "diagnostico": "Gastritis"}
    terms = apply_prior_clinical_safety(historial, rows)
    assert "Ibuprofeno" in historial["alergias"]
    assert terms == ["ibuprofeno"]


def test_medication_conflicts_allergy():
    assert medication_conflicts_allergy("Ibuprofeno 400mg", ["ibuprofeno"])
    assert not medication_conflicts_allergy("Acetaminofén 500mg", ["ibuprofeno"])


def test_enrich_historial_excludes_allergic_medications():
    from app.db.database import SessionLocal

    db = SessionLocal()
    try:
        service = MedicamentosService()
        historial = {"diagnostico": "Cefalea"}
        enriched = service.enrich_historial(
            db, eps_id=1, historial_dict=historial, allergy_terms=["ibuprofeno"]
        )
        names = [
            m["nombre"]
            for m in enriched["medicamentos"]["disponibles_eps"]
            + enriched["medicamentos"]["ideales_sugeridos"]
        ]
        assert all("ibuprofeno" not in n.lower() for n in names)
    finally:
        db.close()


def test_collect_known_allergies_from_multiple_visits():
    rows = [
        _make_historial(consulta_id=2, alergias="Penicilina"),
        _make_historial(consulta_id=1, alergias="Ibuprofeno"),
    ]
    assert collect_known_allergies(rows) == ["penicilina", "ibuprofeno"]
