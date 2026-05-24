from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List
from app.db.database import get_db
from app.models.db_models import MedicamentoEPS
from app.models.schemas import MedicamentoResponse

router = APIRouter(prefix="/medicamentos", tags=["medicamentos"])

@router.get("", response_model=List[MedicamentoResponse])
def get_medicamentos(diagnostico: str | None = None, db: Session = Depends(get_db)):
    query = db.query(MedicamentoEPS)
    if diagnostico:
        # Mock filtering by diagnostico for the hackathon
        # Usually requires a relationship or a full-text search
        query = query.filter(MedicamentoEPS.descripcion.ilike(f"%{diagnostico}%"))
    return query.all()
