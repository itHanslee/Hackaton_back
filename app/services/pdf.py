import os
from dataclasses import dataclass
from io import BytesIO

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer

from app.core.config import get_settings
from app.models.db_models import EPS, Historial, Medico


@dataclass
class PdfContext:
    medico: Medico | None = None
    eps: EPS | None = None


def _format_medicamentos(medicamentos) -> str:
    if not medicamentos:
        return "N/A"

    if isinstance(medicamentos, dict):
        lines: list[str] = []
        disponibles = medicamentos.get("disponibles_eps") or []
        ideales = medicamentos.get("ideales_sugeridos") or []

        if disponibles:
            lines.append("<b>Disponibles EPS:</b>")
            for med in disponibles:
                name = med.get("nombre", str(med)) if isinstance(med, dict) else str(med)
                lines.append(f"• {name}")

        if ideales:
            lines.append("<b>Ideales sugeridos:</b>")
            for med in ideales:
                name = med.get("nombre", str(med)) if isinstance(med, dict) else str(med)
                lines.append(f"• {name}")

        if not lines:
            return "N/A"
        return "<br/>".join(lines)

    if isinstance(medicamentos, list):
        return "<br/>".join(f"• {item}" for item in medicamentos) or "N/A"

    return str(medicamentos)


def _extract_field(medicamentos, key: str) -> str | None:
    if isinstance(medicamentos, dict):
        value = medicamentos.get(key)
        if value:
            return str(value)
    return None


def _append_image_if_exists(story: list, path: str | None, width: float, height: float) -> None:
    if path and os.path.isfile(path):
        story.append(Image(path, width=width, height=height))
        story.append(Spacer(1, 8))


def generate_pdf(historial: Historial, context: PdfContext | None = None) -> str:
    """Genera un PDF a partir del objeto Historial y lo guarda en el sistema de archivos."""
    ctx = context or PdfContext()
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    title_style = styles["Heading1"]
    normal_style = styles["Normal"]

    if ctx.eps and ctx.eps.logo_path:
        _append_image_if_exists(story, ctx.eps.logo_path, 80, 40)

    created = getattr(historial, "created_at", None)
    created_str = created.strftime("%Y-%m-%d") if created else "N/A"
    story.append(Paragraph(f"Historial Clínico - {created_str}", title_style))
    if ctx.eps:
        story.append(Paragraph(f"<b>EPS:</b> {ctx.eps.nombre}", normal_style))
    story.append(Spacer(1, 12))

    story.append(Paragraph(f"<b>Consulta ID:</b> {historial.consulta_id}", normal_style))
    story.append(Spacer(1, 12))

    story.append(Paragraph("<b>Motivo:</b>", styles["Heading2"]))
    story.append(Paragraph(str(historial.motivo_consulta or ""), normal_style))
    story.append(Spacer(1, 12))

    story.append(Paragraph("<b>Síntomas:</b>", styles["Heading2"]))
    story.append(Paragraph(str(historial.sintomas or ""), normal_style))
    story.append(Spacer(1, 12))

    story.append(Paragraph("<b>Diagnóstico:</b>", styles["Heading2"]))
    story.append(Paragraph(str(historial.diagnostico or ""), normal_style))
    story.append(Spacer(1, 12))

    story.append(Paragraph("<b>Plan:</b>", styles["Heading2"]))
    story.append(Paragraph(str(historial.plan_tratamiento or ""), normal_style))
    story.append(Spacer(1, 12))

    meds = historial.medicamentos_sugeridos
    alergias = _extract_field(meds, "alergias")
    notas = _extract_field(meds, "notas_adicionales")

    story.append(Paragraph("<b>Alergias:</b>", styles["Heading2"]))
    story.append(Paragraph(alergias or "N/A", normal_style))
    story.append(Spacer(1, 12))

    story.append(Paragraph("<b>Notas adicionales:</b>", styles["Heading2"]))
    story.append(Paragraph(notas or "N/A", normal_style))
    story.append(Spacer(1, 12))

    story.append(Paragraph("<b>Medicamentos:</b>", styles["Heading2"]))
    story.append(Paragraph(_format_medicamentos(meds), normal_style))
    story.append(Spacer(1, 24))

    if ctx.medico:
        story.append(Paragraph("<b>Firma del médico tratante:</b>", styles["Heading2"]))
        _append_image_if_exists(story, ctx.medico.firma_path, 120, 50)
        story.append(
            Paragraph(
                f"<b>Dr(a). {ctx.medico.nombre}</b><br/>"
                f"{ctx.medico.especialidad}<br/>"
                f"Reg. {ctx.medico.cedula}",
                normal_style,
            )
        )

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()

    settings = get_settings()
    pdf_dir = os.path.abspath(settings.pdf_output_dir)
    os.makedirs(pdf_dir, exist_ok=True)
    pdf_path = os.path.join(pdf_dir, f"historial_{historial.id}.pdf")
    with open(pdf_path, "wb") as f:
        f.write(pdf_bytes)
    return pdf_path


def generate_historial_pdf(historial: Historial, context: PdfContext | None = None) -> str:
    """Wrapper de compatibilidad que llama a generate_pdf."""
    return generate_pdf(historial, context=context)
