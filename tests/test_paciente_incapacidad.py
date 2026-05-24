"""Tests de campos incapacidad en paciente y prueba de radicaciones."""

from datetime import datetime

import pytest

from app.db.database import SessionLocal
from app.models.db_models import EPS, IncapacidadRadicacionJob, Paciente
from app.services.paciente_incapacidad import (
    PACIENTE_INCAPACIDAD_FIELD_KEYS,
    append_radicacion_proof,
    build_paciente_incapacidad_datos,
    sync_paciente_incapacidad_datos,
)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def paciente_melanys(db):
    eps = db.query(EPS).filter(EPS.nombre == "SALUD TOTAL EPS").first()
    if not eps:
        eps = EPS(nombre="SALUD TOTAL EPS")
        db.add(eps)
        db.flush()

    cedula = "1002022473"
    paciente = db.query(Paciente).filter(Paciente.cedula == cedula).first()
    if paciente:
        return paciente, eps

    p = Paciente(
        cedula=cedula,
        nombre="MELANYS PAOLA JIMENEZ SANCHEZ",
        fecha_nacimiento="2000-08-23",
        genero="F",
        tipo_documento="CC",
        tipo_paciente="Contributivo",
        telefono="3000000000",
        eps_id=eps.id,
        datos_incapacidad_json={
            "entidad_codigo": "EPS002",
            "grupo_servicio": "ConsultaExterna",
            "modalidad_servicio": "Intramural",
            "origen": "Comun",
        },
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p, eps


def test_build_paciente_incapacidad_datos_melanys_format(paciente_melanys):
    paciente, eps = paciente_melanys
    datos = build_paciente_incapacidad_datos(paciente, eps)

    for key in PACIENTE_INCAPACIDAD_FIELD_KEYS:
        assert key in datos

    assert datos["paciente_nombre"] == "MELANYS PAOLA JIMENEZ SANCHEZ"
    assert datos["paciente_numero_documento"] == "1002022473"
    assert datos["paciente_tipo_documento"] == "CC"
    assert datos["tipo_paciente"] == "Contributivo"
    assert datos["sexo"] == "Femenino"
    assert datos["eps_detectada"] == "SALUD TOTAL EPS"
    assert datos["entidad_codigo"] == "EPS002"
    assert datos["grupo_servicio"] == "ConsultaExterna"


def test_sync_paciente_incapacidad_datos_persists(db, paciente_melanys):
    paciente, eps = paciente_melanys
    sync_paciente_incapacidad_datos(db, paciente, eps)
    db.refresh(paciente)
    assert paciente.datos_incapacidad_json["paciente_nombre"] == paciente.nombre


def test_append_radicacion_proof(db, paciente_melanys):
    paciente, _ = paciente_melanys
    paciente.radicaciones_json = []
    db.commit()

    job = IncapacidadRadicacionJob(
        historial_id=99,
        medico_id=1,
        estado="completo",
        paso_actual=4,
        ocr_json={"numero_incapacidad": "20274"},
        rethus_json={"status": "success"},
        adres_json={"status": "success"},
        reporte_json={"score_global": 100},
        score=100,
        recomendacion="OK",
        updated_at=datetime.utcnow(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    append_radicacion_proof(db, paciente.id, job, ocr_data=job.ocr_json)
    db.refresh(paciente)

    assert isinstance(paciente.radicaciones_json, list)
    assert len(paciente.radicaciones_json) == 1
    proof = paciente.radicaciones_json[0]
    assert proof["job_id"] == job.id
    assert proof["historial_id"] == 99
    assert proof["numero_incapacidad"] == "20274"
    assert proof["estado"] == "completo"
    assert proof["score"] == 100
    assert proof["reporte"]["score_global"] == 100
