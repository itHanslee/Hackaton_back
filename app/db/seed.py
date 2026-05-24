from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.db_models import (
    Cita,
    EPS,
    Medico,
    MedicamentoEPS,
    Paciente,
)


def ensure_auth_credentials(db: Session) -> None:
    """Asigna email/password demo si faltan (BD compartida ya sembrada)."""
    demo_emails = {
        "1001": "ana.garcia@medinote.local",
        "1002": "luis.perez@medinote.local",
        "1003": "maria.lopez@medinote.local",
        "2001": "carlos.rodriguez@example.com",
        "2002": "laura.martinez@example.com",
    }
    changed = False
    for medico in db.query(Medico).all():
        if not medico.password_hash:
            medico.password_hash = hash_password("medico123")
            changed = True
        if not medico.email:
            medico.email = demo_emails.get(medico.cedula, f"medico{medico.id}@medinote.local")
            changed = True
    for paciente in db.query(Paciente).all():
        if not paciente.password_hash:
            paciente.password_hash = hash_password("paciente123")
            changed = True
        if not paciente.email:
            paciente.email = demo_emails.get(
                paciente.cedula, f"paciente{paciente.id}@example.com"
            )
            changed = True
    if changed:
        db.commit()


def seed_database(db: Session) -> None:
    if db.query(EPS).filter(EPS.nombre == "Sura").first() is not None:
        ensure_auth_credentials(db)
        return

    sura = EPS(nombre="Sura")
    sanitas = EPS(nombre="Sanitas")
    db.add_all([sura, sanitas])
    db.flush()

    medicos = [
        Medico(
            cedula="1001",
            nombre="Dr. Ana García",
            especialidad="Medicina General",
            eps_id=sura.id,
            email="ana.garcia@medinote.local",
            password_hash=hash_password("medico123"),
        ),
        Medico(
            cedula="1002",
            nombre="Dr. Luis Pérez",
            especialidad="Cardiología",
            eps_id=sura.id,
            email="luis.perez@medinote.local",
            password_hash=hash_password("medico123"),
        ),
        Medico(
            cedula="1003",
            nombre="Dra. María López",
            especialidad="Endocrinología",
            eps_id=sanitas.id,
            email="maria.lopez@medinote.local",
            password_hash=hash_password("medico123"),
        ),
    ]
    db.add_all(medicos)
    db.flush()

    pacientes = [
        Paciente(
            cedula="2001",
            nombre="Carlos Rodríguez",
            fecha_nacimiento="1985-03-12",
            genero="M",
            tipo_documento="CC",
            tipo_paciente="Contributivo",
            telefono="3001234567",
            email="carlos.rodriguez@example.com",
            password_hash=hash_password("paciente123"),
            eps_id=sura.id,
            datos_incapacidad_json={
                "entidad_codigo": "EPS001",
                "grupo_servicio": "ConsultaExterna",
                "modalidad_servicio": "Intramural",
                "origen": "Comun",
            },
        ),
        Paciente(
            cedula="2002",
            nombre="Laura Martínez",
            fecha_nacimiento="1992-07-25",
            genero="F",
            tipo_documento="CC",
            tipo_paciente="Contributivo",
            telefono="3017654321",
            email="laura.martinez@example.com",
            password_hash=hash_password("paciente123"),
            eps_id=sanitas.id,
            datos_incapacidad_json={
                "entidad_codigo": "EPS002",
                "grupo_servicio": "ConsultaExterna",
                "modalidad_servicio": "Intramural",
                "origen": "Comun",
            },
        ),
    ]
    db.add_all(pacientes)
    db.flush()

    medicamentos = [
        MedicamentoEPS(
            nombre="Losartán 50mg",
            descripcion="Antihipertensivo",
            nombre_generico="Losartán",
            nombre_comercial="Losartán MK",
            categoria="Cardiovascular",
            diagnosticos_aplica=["Hipertensión", "Presión arterial alta"],
            disponible=True,
            eps_id=sura.id,
        ),
        MedicamentoEPS(
            nombre="Enalapril 10mg",
            descripcion="IECA para hipertensión",
            nombre_generico="Enalapril",
            nombre_comercial="Enalapril Genfar",
            categoria="Cardiovascular",
            diagnosticos_aplica=["Hipertensión"],
            disponible=True,
            eps_id=sura.id,
        ),
        MedicamentoEPS(
            nombre="Amlodipino 5mg",
            descripcion="Calcioantagonista",
            nombre_generico="Amlodipino",
            nombre_comercial="Amlodipino La Santé",
            categoria="Cardiovascular",
            diagnosticos_aplica=["Hipertensión", "Angina"],
            disponible=False,
            eps_id=sura.id,
        ),
        MedicamentoEPS(
            nombre="Metformina 850mg",
            descripcion="Antidiabético oral",
            nombre_generico="Metformina",
            nombre_comercial="Metformina MK",
            categoria="Endocrino",
            diagnosticos_aplica=["Diabetes", "Diabetes mellitus tipo 2"],
            disponible=True,
            eps_id=sura.id,
        ),
        MedicamentoEPS(
            nombre="Glibenclamida 5mg",
            descripcion="Antidiabético oral",
            nombre_generico="Glibenclamida",
            nombre_comercial="Glibenclamida Genfar",
            categoria="Endocrino",
            diagnosticos_aplica=["Diabetes"],
            disponible=False,
            eps_id=sura.id,
        ),
        MedicamentoEPS(
            nombre="Acetaminofén 500mg",
            descripcion="Analgésico y antipirético",
            nombre_generico="Acetaminofén",
            nombre_comercial="Dolex",
            categoria="Analgesia",
            diagnosticos_aplica=["Cefalea", "Dolor leve", "Fiebre"],
            disponible=True,
            eps_id=sura.id,
        ),
        MedicamentoEPS(
            nombre="Ibuprofeno 400mg",
            descripcion="AINE",
            nombre_generico="Ibuprofeno",
            nombre_comercial="Advil",
            categoria="Analgesia",
            diagnosticos_aplica=["Cefalea", "Dolor muscular"],
            disponible=True,
            eps_id=sanitas.id,
        ),
        MedicamentoEPS(
            nombre="Atorvastatina 20mg",
            descripcion="Hipolipemiante",
            nombre_generico="Atorvastatina",
            nombre_comercial="Atorvastatina La Santé",
            categoria="Cardiovascular",
            diagnosticos_aplica=["Dislipidemia", "Colesterol alto"],
            disponible=True,
            eps_id=sanitas.id,
        ),
        MedicamentoEPS(
            nombre="Rosuvastatina 10mg",
            descripcion="Estatinas de alta potencia",
            nombre_generico="Rosuvastatina",
            nombre_comercial="Crestor",
            categoria="Cardiovascular",
            diagnosticos_aplica=["Dislipidemia"],
            disponible=False,
            eps_id=sanitas.id,
        ),
        MedicamentoEPS(
            nombre="Salbutamol inhalador",
            descripcion="Broncodilatador",
            nombre_generico="Salbutamol",
            nombre_comercial="Ventolin",
            categoria="Respiratorio",
            diagnosticos_aplica=["Asma", "EPOC"],
            disponible=True,
            eps_id=sanitas.id,
        ),
        MedicamentoEPS(
            nombre="Omeprazol 20mg",
            descripcion="Inhibidor de bomba de protones",
            nombre_generico="Omeprazol",
            nombre_comercial="Omeprazol MK",
            categoria="Gastrointestinal",
            diagnosticos_aplica=["Gastritis", "Reflujo gastroesofágico"],
            disponible=True,
            eps_id=sanitas.id,
        ),
        MedicamentoEPS(
            nombre="Levotiroxina 100mcg",
            descripcion="Hormona tiroidea",
            nombre_generico="Levotiroxina",
            nombre_comercial="Euthyrox",
            categoria="Endocrino",
            diagnosticos_aplica=["Hipotiroidismo"],
            disponible=True,
            eps_id=sura.id,
        ),
    ]
    db.add_all(medicamentos)

    tomorrow = datetime.utcnow().replace(hour=10, minute=0, second=0, microsecond=0)
    tomorrow += timedelta(days=1)
    sample_cita = Cita(
        paciente_id=pacientes[0].id,
        medico_id=medicos[0].id,
        fecha_hora=tomorrow,
        motivo="Control de hipertensión",
        estado="pendiente",
    )
    db.add(sample_cita)
    db.commit()
