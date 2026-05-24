from sqlalchemy.orm import Session

from app.models.db_models import MedicamentoEPS
from app.services.clinical_context import medication_conflicts_allergy


class MedicamentosService:
    @staticmethod
    def _serialize_medicamento(medicamento: MedicamentoEPS) -> dict:
        return {
            "id": medicamento.id,
            "nombre": medicamento.nombre,
            "descripcion": medicamento.descripcion,
            "nombre_generico": medicamento.nombre_generico,
            "nombre_comercial": medicamento.nombre_comercial,
            "categoria": medicamento.categoria,
            "diagnosticos_aplica": medicamento.diagnosticos_aplica or [],
            "disponible": medicamento.disponible,
            "eps_id": medicamento.eps_id,
        }

    @staticmethod
    def _matches_diagnostico(medicamento: MedicamentoEPS, diagnostico: str) -> bool:
        if not medicamento.diagnosticos_aplica:
            return False
        needle = diagnostico.lower()
        return any(needle in item.lower() for item in medicamento.diagnosticos_aplica)

    def get_by_diagnostico(
        self, db: Session, eps_id: int, diagnostico: str
    ) -> dict[str, list[dict]]:
        medicamentos = (
            db.query(MedicamentoEPS)
            .filter(MedicamentoEPS.eps_id == eps_id)
            .all()
        )

        matched = [
            medicamento
            for medicamento in medicamentos
            if self._matches_diagnostico(medicamento, diagnostico)
        ]

        disponibles_eps = [
            self._serialize_medicamento(medicamento)
            for medicamento in matched
            if medicamento.disponible
        ]
        ideales_sugeridos = [
            self._serialize_medicamento(medicamento)
            for medicamento in matched
            if not medicamento.disponible
        ]

        return {
            "disponibles_eps": disponibles_eps,
            "ideales_sugeridos": ideales_sugeridos,
        }

    def _filter_by_allergies(
        self, meds: dict[str, list[dict]], allergy_terms: list[str]
    ) -> tuple[dict[str, list[dict]], list[str]]:
        if not allergy_terms:
            return meds, []

        excluded: list[str] = []

        def _keep(med: dict) -> bool:
            name = med.get("nombre") or med.get("nombre_generico") or med.get("nombre_comercial") or ""
            if medication_conflicts_allergy(str(name), allergy_terms):
                excluded.append(str(name))
                return False
            return True

        filtered = {
            "disponibles_eps": [m for m in meds.get("disponibles_eps", []) if _keep(m)],
            "ideales_sugeridos": [m for m in meds.get("ideales_sugeridos", []) if _keep(m)],
        }
        return filtered, excluded

    def enrich_historial(
        self,
        db: Session,
        eps_id: int,
        historial_dict: dict,
        allergy_terms: list[str] | None = None,
    ) -> dict:
        diagnostico = historial_dict.get("diagnostico", "")
        meds = self.get_by_diagnostico(db, eps_id, diagnostico)
        filtered, excluded = self._filter_by_allergies(meds, allergy_terms or [])
        historial_dict["medicamentos"] = filtered
        if excluded:
            historial_dict["medicamentos_excluidos_por_alergia"] = excluded
        return historial_dict
