from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.models.db_models import Consulta, Historial
from app.services.pdf import generate_pdf
from app.models.schemas import GenerateHistorialRequest, GenerateHistorialResponseData
import shutil
import uuid
import os

router = APIRouter(prefix="/consultas", tags=["consultas"])

@router.post("/procesar", response_model=GenerateHistorialResponseData)
async def procesar_consulta(request: GenerateHistorialRequest = Depends(), db: Session = Depends(get_db)):
    # Simulación: crear consulta, transcripción y generar historial
    consulta = Consulta(audio_path="placeholder", transcripcion=request.transcript)
    db.add(consulta)
    db.commit()
    db.refresh(consulta)
    # Generar historial ficticio
    historial = Historial(
        consulta_id=consulta.id,
        motivo_consulta=request.transcript[:200],
        sintomas="",
        diagnostico="",
        plan_tratamiento="",
        medicamentos_sugeridos="",
        confirmado_por_medico=False,
    )
    db.add(historial)
    db.commit()
    db.refresh(historial)
    # Generar PDF (placeholder path)
    pdf_path = generate_pdf(historial)
    historial.pdf_path = pdf_path
    db.commit()
    # Return response
    return GenerateHistorialResponseData(
        historial_id=historial.id,
        historial=historial,
        session_id=str(uuid.uuid4())
    )
