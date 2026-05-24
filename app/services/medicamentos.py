import re

from sqlalchemy.orm import Session

from app.models.db_models import MedicamentoEPS
from app.models.schemas import NO_DEFINIDO
from app.services.clinical_context import medication_conflicts_allergy


class MedicamentosService:
    @staticmethod
    def _extract_dosis(nombre: str, descripcion: str | None = None) -> str:
        for source in (nombre, descripcion or ""):
            match = re.search(r"(\d+\s*(?:mg|mcg|ml|g|UI|%))", source, re.I)
            if match:
                return match.group(1).replace(" ", "")
        return "Según indicación médica"

    @staticmethod
    def _default_frecuencia(categoria: str | None) -> str:
        cat = (categoria or "").lower()
        if "cardiovascular" in cat or "endocrino" in cat:
            return "1 vez al día"
        if "analgesia" in cat:
            return "Cada 8 horas si hay dolor"
        if "respiratorio" in cat:
            return "Según necesidad (inhalaciones)"
        if "gastrointestinal" in cat:
            return "1 vez al día en ayunas"
        return "Según prescripción médica"

    @classmethod
    def _serialize_medicamento(cls, medicamento: MedicamentoEPS) -> dict:
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

    @classmethod
    def _to_disponible(cls, medicamento: dict) -> dict:
        nombre = medicamento.get("nombre") or medicamento.get("nombre_generico") or NO_DEFINIDO
        descripcion = medicamento.get("descripcion") or ""
        return {
            "nombre": nombre,
            "dosis": cls._extract_dosis(nombre, descripcion),
            "frecuencia": cls._default_frecuencia(medicamento.get("categoria")),
            "nombre_generico": medicamento.get("nombre_generico"),
            "descripcion": descripcion,
            "categoria": medicamento.get("categoria"),
            "disponible_eps": True,
        }

    @classmethod
    def _to_ideal(cls, medicamento: dict) -> dict:
        nombre = medicamento.get("nombre") or medicamento.get("nombre_generico") or NO_DEFINIDO
        generico = medicamento.get("nombre_generico") or nombre
        descripcion = medicamento.get("descripcion") or "Medicamento de referencia clínica"
        return {
            "nombre": nombre,
            "razon": (
                f"No disponible en el formulario EPS. "
                f"Alternativa clínica sugerida: {generico}. {descripcion}."
            ),
            "nombre_generico": generico,
            "descripcion": descripcion,
            "disponible_eps": False,
        }

    @staticmethod
    def _matches_diagnostico(medicamento: MedicamentoEPS, diagnostico: str) -> bool:
        if not medicamento.diagnosticos_aplica or not diagnostico.strip():
            return False
        diag = diagnostico.lower()
        for item in medicamento.diagnosticos_aplica:
            label = item.lower().strip()
            if not label:
                continue
            if label in diag or diag in label:
                return True
            for token in re.split(r"[\s,;/\-—()]+", label):
                token = token.strip()
                if len(token) >= 4 and token in diag:
                    return True
        return False

    def list_formulary_summary(self, db: Session, eps_id: int) -> str:
        medicamentos = (
            db.query(MedicamentoEPS)
            .filter(MedicamentoEPS.eps_id == eps_id)
            .order_by(MedicamentoEPS.nombre.asc())
            .all()
        )
        if not medicamentos:
            return "Sin medicamentos registrados para esta EPS."
        lines: list[str] = []
        for med in medicamentos:
            dx = ", ".join(med.diagnosticos_aplica or [])
            estado = "DISPONIBLE en EPS" if med.disponible else "NO disponible en EPS"
            lines.append(
                f"- {med.nombre} | genérico: {med.nombre_generico or 'N/D'} | "
                f"{estado} | diagnósticos: {dx or 'general'}"
            )
        return "\n".join(lines)

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

        serialized = [self._serialize_medicamento(m) for m in matched]
        return {
            "disponibles_eps": [m for m in serialized if m.get("disponible")],
            "ideales_sugeridos": [m for m in serialized if not m.get("disponible")],
        }

    def _filter_by_allergies(
        self, meds: dict[str, list[dict]], allergy_terms: list[str]
    ) -> tuple[dict[str, list[dict]], list[str]]:
        if not allergy_terms:
            return meds, []

        excluded: list[str] = []

        def _keep(med: dict) -> bool:
            name = (
                med.get("nombre")
                or med.get("nombre_generico")
                or med.get("nombre_comercial")
                or ""
            )
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
        db_meds = self.get_by_diagnostico(db, eps_id, diagnostico)
        filtered, excluded = self._filter_by_allergies(db_meds, allergy_terms or [])

        ai_meds = historial_dict.get("medicamentos")
        if not isinstance(ai_meds, dict):
            ai_meds = {"disponibles_eps": [], "ideales_sugeridos": []}

        db_disponibles = [self._to_disponible(m) for m in filtered.get("disponibles_eps", [])]
        db_ideales = [self._to_ideal(m) for m in filtered.get("ideales_sugeridos", [])]

        if db_disponibles or db_ideales:
            historial_dict["medicamentos"] = {
                "disponibles_eps": db_disponibles,
                "ideales_sugeridos": db_ideales,
            }
        elif ai_meds.get("disponibles_eps") or ai_meds.get("ideales_sugeridos"):
            historial_dict["medicamentos"] = ai_meds
        else:
            historial_dict["medicamentos"] = {
                "disponibles_eps": [],
                "ideales_sugeridos": [],
            }

        if excluded:
            historial_dict["medicamentos_excluidos_por_alergia"] = excluded
        return historial_dict
