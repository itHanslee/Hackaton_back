# Auditoría de estructura — MediNote Backend

> Aplicado según `agency-agents/agente_auditoria_clean_code_poo.md` (SRP, capas, DRY, un solo punto de entrada).

## Decisión: un solo backend

| Antes | Después |
|-------|---------|
| `app/` + `backend/` + `_backup_extract/` | Solo `app/` |
| `chatbot_agent/` microservicio | `app/routers/agent.py` + `app/services/chat_agent.py` |
| `/transcribe` en router agent | `app/routers/transcribe.py` (toda STT junta) |

## Capas (FastAPI)

```
routers/     → Presentación (HTTP/WS, validación entrada)
services/    → Lógica de negocio e integraciones (IA, email, PDF)
models/      → Dominio (db_models, schemas)
db/          → Infraestructura persistencia
core/        → Config, auth, utilidades transversales
```

## Entry point

```powershell
uvicorn app.main:app --reload --port 8000
```

## Checklist post-auditoría

- [x] Un solo backend ejecutable (`app/main.py`)
- [x] Carpeta `backend/` eliminada o gitignored (legacy)
- [x] Backup `_backup_extract/` eliminado
- [x] Agente conversacional integrado (no microservicio)
- [x] Transcribe REST + WS en un router
- [x] 34 tests passing
- [ ] Refactor futuro: extraer repositorios si crece complejidad (Repository pattern del agente POO)

## Métricas objetivo (agente auditoría)

| Métrica | Objetivo |
|---------|----------|
| Cobertura tests | > 80% (actual: suite de 34 tests) |
| Funciones > 50 líneas | Revisar `historiales.py`, `chat_agent.py` en siguiente iteración |
| Duplicación `app/` vs `backend/` | 0% (backend eliminado) |
