import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from app.core.config import Settings, get_settings
from app.models.db_models import Historial, Paciente

logger = logging.getLogger(__name__)


def _format_medicamentos(medicamentos: dict[str, Any] | None) -> str:
    if not medicamentos:
        return "No definido"

    lines: list[str] = []
    disponibles = medicamentos.get("disponibles_eps") or []
    if isinstance(disponibles, list) and disponibles:
        lines.append("Medicamentos disponibles en su EPS:")
        for med in disponibles:
            if isinstance(med, dict):
                nombre = med.get("nombre") or med.get("nombre_comercial") or "—"
                dosis = med.get("dosis") or med.get("descripcion") or ""
                freq = med.get("frecuencia") or ""
                extra = " — ".join(x for x in (dosis, freq) if x)
                lines.append(f"  • {nombre}" + (f" ({extra})" if extra else ""))
            else:
                lines.append(f"  • {med}")

    ideales = medicamentos.get("ideales_sugeridos") or []
    if isinstance(ideales, list) and ideales:
        lines.append("")
        lines.append("Medicamentos sugeridos:")
        for med in ideales:
            if isinstance(med, dict):
                nombre = med.get("nombre") or "—"
                razon = med.get("razon") or ""
                lines.append(f"  • {nombre}" + (f": {razon}" if razon else ""))
            else:
                lines.append(f"  • {med}")

    return "\n".join(lines) if lines else "No definido"


def build_historial_email(
    paciente: Paciente,
    historial: Historial,
    *,
    requiere_incapacidad: bool = False,
    incapacidad_dias: int | None = None,
) -> tuple[str, str]:
    meds = historial.medicamentos_sugeridos or {}
    sintomas = historial.sintomas or "No definido"

    incapacidad_block = ""
    if requiere_incapacidad:
        dias = incapacidad_dias or 0
        incapacidad_block = (
            f"\n\nINCAPACIDAD MÉDICA\n"
            f"Se le otorga incapacidad médica por {dias} día(s), "
            f"contados a partir de la fecha de la consulta.\n"
        )

    body = f"""Estimado/a {paciente.nombre},

Su consulta médica en MediNote ha sido registrada y confirmada por el médico tratante.

RESUMEN DE LA CONSULTA
Motivo: {historial.motivo_consulta}
Síntomas: {sintomas}
Diagnóstico: {historial.diagnostico}
Plan de tratamiento: {historial.plan_tratamiento}
{incapacidad_block}
MEDICAMENTOS
{_format_medicamentos(meds)}

Puede descargar el reporte completo en PDF desde la plataforma MediNote.

Saludos,
Equipo MediNote
"""
    subject = f"MediNote — Reporte de consulta ({historial.diagnostico})"
    return subject, body


def send_historial_email(
    paciente: Paciente,
    historial: Historial,
    *,
    requiere_incapacidad: bool = False,
    incapacidad_dias: int | None = None,
    settings: Settings | None = None,
) -> bool:
    cfg = settings or get_settings()
    if not cfg.smtp_enabled:
        logger.info("SMTP deshabilitado; correo no enviado a %s", paciente.email)
        return False
    if not paciente.email:
        logger.warning("Paciente %s sin email; correo no enviado", paciente.id)
        return False

    subject, body = build_historial_email(
        paciente,
        historial,
        requiere_incapacidad=requiere_incapacidad,
        incapacidad_dias=incapacidad_dias,
    )

    msg = MIMEMultipart()
    msg["From"] = cfg.smtp_from
    msg["To"] = paciente.email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=20) as server:
            if cfg.smtp_use_tls:
                server.starttls()
            if cfg.smtp_user and cfg.smtp_password:
                server.login(cfg.smtp_user, cfg.smtp_password)
            server.send_message(msg)
        logger.info("Correo de historial enviado a %s", paciente.email)
        return True
    except Exception:
        logger.exception("Error enviando correo a %s", paciente.email)
        return False
