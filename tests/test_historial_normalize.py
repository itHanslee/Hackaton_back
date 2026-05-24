import pytest

from app.models.schemas import NO_DEFINIDO
from app.services.ai import _normalize_historial_data


def test_normalize_medicamentos_string_lists():
    data = {
        "motivo_consulta": "Cefalea",
        "sintomas": ["Dolor"],
        "diagnostico": "Cefalea tensional",
        "plan_tratamiento": "Reposo",
        "medicamentos": {
            "disponibles_eps": [],
            "ideales_sugeridos": NO_DEFINIDO,
        },
    }
    normalized = _normalize_historial_data(data)
    assert normalized["medicamentos"]["ideales_sugeridos"] == []
