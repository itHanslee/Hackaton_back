# Database indexes and migrations

MediNote manages schema with **Alembic** (default) and applies performance indexes after each upgrade via `ensure_indexes()` (`app/db/indexes.py`).

## Alembic (default)

Set in `.env`:

```env
USE_ALEMBIC=true
DATABASE_URL=sqlite:///./medinote.db
```

On startup (`app/main.py`), when `USE_ALEMBIC=true`, the app runs `alembic upgrade head` through `app/db/migrate.py`, then creates indexes with `IF NOT EXISTS`.

### CLI

From the project root:

```bash
# Apply pending migrations
alembic upgrade head

# Create a new migration after model changes
alembic revision --autogenerate -m "describe change"

# Mark an existing DB as up-to-date (without running DDL)
alembic stamp head
```

### Existing databases (schema_sync → Alembic)

If the database already has MediNote tables but no `alembic_version` table, startup detects this and runs **`stamp head`** automatically so existing deployments are not broken.

To force a fresh migration on an empty database, use `alembic upgrade head`.

### Tests

Pytest sets `USE_ALEMBIC=false` and uses `create_all` / `drop_all` for speed (`tests/conftest.py`).

### Legacy mode

```env
USE_ALEMBIC=false
```

Falls back to `app/db/schema_sync.py` (`create_all` + column patches).

## Indexes

| Table | Index | Columns | Purpose |
|-------|-------|---------|---------|
| `citas` | `idx_citas_paciente_id` | `paciente_id` | Filter appointments by patient |
| `citas` | `idx_citas_medico_id` | `medico_id` | Filter appointments by doctor |
| `citas` | `idx_citas_fecha_hora` | `fecha_hora` | Sort or filter by schedule |
| `consultas` | `idx_consultas_cita_id` | `cita_id` | Join consultas → citas |
| `historiales` | `idx_historiales_consulta_id` | `consulta_id` | Join historiales → consultas |
| `historiales` | `idx_historiales_created_at_desc` | `created_at DESC` | Recent-first historial ordering |

## Query path: prior clinical context

`fetch_prior_historiales` (`app/services/clinical_context.py`) loads a patient's confirmed historiales for AI safety context:

```
Historial → Consulta (consulta_id)
         → Cita (cita_id)
         → filter Cita.paciente_id = ?
         → order by Historial.created_at DESC
```

Relevant indexes:

- `idx_citas_paciente_id` — narrows citas for the patient before joining consultas/historiales
- `idx_consultas_cita_id` — join consultas to matching citas
- `idx_historiales_consulta_id` — join historiales to consultas
- `idx_historiales_created_at_desc` — supports descending sort on recent visits

Other `citas` indexes (`medico_id`, `fecha_hora`) support listing and scheduling queries outside the historial path.
