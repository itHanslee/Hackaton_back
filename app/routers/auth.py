from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.responses import error_response, ok
from app.core.security import create_access_token, verify_password
from app.db.database import get_db
from app.models.db_models import Medico, Paciente

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    cedula: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


@router.post("/paciente/login")
def login_paciente(body: LoginRequest, db: Session = Depends(get_db)):
    paciente = db.query(Paciente).filter(Paciente.cedula == body.cedula.strip()).first()
    if not paciente or not verify_password(body.password, paciente.password_hash or ""):
        return error_response("INVALID_CREDENTIALS", "Cédula o contraseña incorrecta.", 401)

    token = create_access_token(
        role="paciente",
        subject_id=paciente.id,
        cedula=paciente.cedula,
        nombre=paciente.nombre,
    )
    return ok(
        {
            "access_token": token,
            "token_type": "bearer",
            "role": "paciente",
            "user_id": paciente.id,
            "nombre": paciente.nombre,
            "email": paciente.email,
        }
    )


@router.post("/medico/login")
def login_medico(body: LoginRequest, db: Session = Depends(get_db)):
    medico = db.query(Medico).filter(Medico.cedula == body.cedula.strip()).first()
    if not medico or not verify_password(body.password, medico.password_hash or ""):
        return error_response("INVALID_CREDENTIALS", "Cédula o contraseña incorrecta.", 401)

    token = create_access_token(
        role="medico",
        subject_id=medico.id,
        cedula=medico.cedula,
        nombre=medico.nombre,
        extra={"especialidad": medico.especialidad},
    )
    return ok(
        {
            "access_token": token,
            "token_type": "bearer",
            "role": "medico",
            "user_id": medico.id,
            "nombre": medico.nombre,
            "email": medico.email,
            "especialidad": medico.especialidad,
        }
    )
