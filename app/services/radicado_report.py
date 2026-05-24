"""Paso 4: reporte final consolidado (misma lógica que dashboard demo)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def build_validation_report(
    ocr: dict[str, Any],
    rethus: dict[str, Any],
    adres: dict[str, Any],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    campos_pdf = {
        "Número de incapacidad": ocr.get("numero_incapacidad"),
        "Fecha de inicio": ocr.get("fecha_inicio"),
        "Fecha de fin": ocr.get("fecha_fin"),
        "Días": ocr.get("dias"),
        "Diagnóstico (CIE-10)": ocr.get("diagnostico_codigo"),
        "Paciente": ocr.get("paciente_nombre"),
        "Cédula paciente": ocr.get("paciente_numero_documento"),
        "EPS detectada": ocr.get("eps_detectada"),
        "Médico": ocr.get("medico_nombre"),
        "Registro médico": ocr.get("registro_medico"),
    }
    for label, value in campos_pdf.items():
        checks.append({"grupo": "PDF / IA", "item": label, "ok": bool(value), "valor": value or "— faltante —"})

    rh_estado = (rethus.get("medico") or {}).get("rethus") or rethus.get("status") or "desconocido"
    rh_ok = rethus.get("status") == "success" or (rethus.get("medico") or {}).get("rethus") == "VALIDADO"
    checks.append({"grupo": "RETHUS", "item": "Médico validado en MinSalud", "ok": rh_ok, "valor": rh_estado})
    if (rethus.get("medico") or {}).get("nombre"):
        checks.append({
            "grupo": "RETHUS",
            "item": "Nombre confirmado",
            "ok": True,
            "valor": rethus["medico"]["nombre"],
        })

    ad_ok = adres.get("status") in {"success", "manual_verification_completed"}
    ad_activo = str(adres.get("estado_afiliacion") or "").upper() == "ACTIVO"
    coincide = adres.get("coincide_con_eps_laravel")
    checks.append({"grupo": "ADRES", "item": "Consulta de afiliación", "ok": ad_ok, "valor": adres.get("status")})
    checks.append({
        "grupo": "ADRES",
        "item": "EPS encontrada en BDUA",
        "ok": bool(adres.get("eps_encontrada")),
        "valor": adres.get("eps_encontrada") or "—",
    })
    checks.append({
        "grupo": "ADRES",
        "item": "Afiliación ACTIVA",
        "ok": ad_activo,
        "valor": adres.get("estado_afiliacion") or "—",
    })
    checks.append({
        "grupo": "ADRES",
        "item": "EPS del PDF coincide con BDUA",
        "ok": coincide is True,
        "valor": "✓ Coincide" if coincide is True else ("⚠ No coincide" if coincide is False else "No comparable"),
    })

    total = len(checks)
    ok_count = sum(1 for c in checks if c["ok"])
    pct = round((ok_count / total) * 100) if total else 0
    completo = ok_count == total and total > 0
    aceptable = pct >= 80

    if completo:
        status = "COMPLETO Y VERIFICADO"
        recomendacion = "La incapacidad puede radicarse automáticamente sin intervención humana."
    elif aceptable:
        status = "APROBADO CON OBSERVACIONES"
        recomendacion = "La incapacidad puede radicarse pero conviene revisar las observaciones marcadas."
    else:
        status = "INCOMPLETO — REQUIERE REVISIÓN HUMANA"
        recomendacion = "La incapacidad NO debe radicarse automáticamente. Asignar a operador humano."

    grupos: dict[str, list[dict[str, Any]]] = {}
    for check in checks:
        grupos.setdefault(check["grupo"], []).append(check)

    return {
        "generado_en": datetime.now(timezone.utc).isoformat(),
        "score_global": pct,
        "status": status,
        "recomendacion": recomendacion,
        "validaciones_aprobadas": ok_count,
        "validaciones_totales": total,
        "checks": checks,
        "grupos": grupos,
        "pdf": ocr,
        "rethus": rethus,
        "adres": adres,
    }
