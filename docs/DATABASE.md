# Database indexes

MediNote applies performance indexes during startup via `sync_schema()` → `ensure_indexes()` (`app/db/indexes.py`). Indexes are created with `CREATE INDEX IF NOT EXISTS`, so the step is safe on SQLite and PostgreSQL and can run repeatedly.

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
