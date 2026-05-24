"""Tests del payload RETHUS en pipeline de radicación."""

from app.services.radicado_pipeline import _merge_ocr


def test_rethus_payload_uses_paciente_documento():
    ocr_data = _merge_ocr(
        {},
        {
            "registro_medico": "1143457721",
            "paciente_numero_documento": "1002022473",
            "paciente_tipo_documento": "CC",
        },
    )
    rethus_payload = {
        "registro_medico": ocr_data.get("registro_medico"),
        "tipo_documento": ocr_data.get("paciente_tipo_documento") or "CC",
        "numero_documento": ocr_data.get("paciente_numero_documento"),
    }
    assert rethus_payload["numero_documento"] == "1002022473"
    assert rethus_payload["registro_medico"] == "1143457721"
