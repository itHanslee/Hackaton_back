from sqlalchemy.orm import Session

from app.models.db_models import MedicamentoEPS


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

    def enrich_historial(
        self, db: Session, eps_id: int, historial_dict: dict
    ) -> dict:
        diagnostico = historial_dict.get("diagnostico", "")
        historial_dict["medicamentos"] = self.get_by_diagnostico(
            db, eps_id, diagnostico
        )
        return historial_dict
