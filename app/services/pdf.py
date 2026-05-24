from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from app.models.db_models import Historial
import os


def generate_pdf(historial: Historial) -> str:
    """Generate a PDF for the given historial and save it to the filesystem.
    Returns the absolute path to the generated PDF file.
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    title_style = styles['Heading1']
    normal_style = styles['Normal']

    # Use creation date if available, else placeholder
    created = getattr(historial, 'created_at', None)
    created_str = created.strftime('%Y-%m-%d') if created else 'N/A'
    story.append(Paragraph(f"Historial Clínico - {created_str}", title_style))
    story.append(Spacer(1, 12))

    # Show Consulta ID (relates to patient/medico via other tables)
    story.append(Paragraph(f"<b>Consulta ID:</b> {historial.consulta_id}", normal_style))
    story.append(Spacer(1, 12))

    story.append(Paragraph("<b>Motivo:</b>", styles['Heading2']))
    story.append(Paragraph(str(historial.motivo_consulta), normal_style))
    story.append(Spacer(1, 12))

    story.append(Paragraph("<b>Síntomas:</b>", styles['Heading2']))
    story.append(Paragraph(str(historial.sintomas), normal_style))
    story.append(Spacer(1, 12))

    story.append(Paragraph("<b>Diagnóstico:</b>", styles['Heading2']))
    story.append(Paragraph(str(historial.diagnostico), normal_style))
    story.append(Spacer(1, 12))

    story.append(Paragraph("<b>Plan:</b>", styles['Heading2']))
    story.append(Paragraph(str(historial.plan_tratamiento), normal_style))
    story.append(Spacer(1, 12))

    story.append(Paragraph("<b>Medicamentos:</b>", styles['Heading2']))
    story.append(Paragraph(str(historial.medicamentos_sugeridos), normal_style))

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()

    # Ensure a directory for PDFs exists
    pdf_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../media/pdfs"))
    os.makedirs(pdf_dir, exist_ok=True)
    pdf_path = os.path.join(pdf_dir, f"historial_{historial.id}.pdf")
    with open(pdf_path, "wb") as f:
        f.write(pdf_bytes)
    return pdf_path

