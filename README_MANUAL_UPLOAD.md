# Backend-definitivo-V5.1 manual upload diff

Questo pacchetto contiene i file nuovi/modificati della build V5.1 deep-stress verified, esclusi report/cache/zip/frontend.

## Come usarlo

1. Scarica ed estrai questo zip.
2. Copia il contenuto della cartella `files/` nella root della repo GitHub locale.
3. Esegui `git status`, test, commit e push.

```bash
rsync -av files/ /path/to/Backend-definitivo-V5/
cd /path/to/Backend-definitivo-V5
python -m compileall -q .
pytest -q tests/pytest_*.py
git status
git add api_app.py pyproject.toml Makefile CHANGELOG.md VERSION engines tests tools docs .github
git commit -m "Integrate Backend V5.1 deep stress verified diff"
git push origin main
```

## Nuovi file

- `.github/workflows/hardening.yml`
- `.github/workflows/multitenant-stress.yml`
- `docs/BACKEND_IMPLEMENTATIONS_V2.md`
- `docs/HARDENING_TESTS.md`
- `docs/MERGE_V5_1_BACKEND.md`
- `docs/MULTI_TENANT_STRESS_TESTING.md`
- `docs/SECURITY_HARDENING_V5_1.md`
- `docs/WORKOUT_SYSTEM_BACKEND_V1.md`
- `docs/workout_db_schema_v1.sql`
- `engines/core/security.py`
- `engines/io/power_source_normalizer.py`
- `engines/load/__init__.py`
- `engines/load/manual_load.py`
- `engines/performance/neuromuscular_profile.py`
- `engines/projection/__init__.py`
- `engines/projection/season_projection_engine.py`
- `engines/twin_state/__init__.py`
- `engines/twin_state/models.py`
- `engines/twin_state/serialization.py`
- `engines/twin_state/state_update_engine.py`
- `engines/workouts/__init__.py`
- `engines/workouts/calendar_engine.py`
- `engines/workouts/compliance_engine.py`
- `engines/workouts/feasibility_engine.py`
- `engines/workouts/models.py`
- `engines/workouts/template_engine.py`
- `tests/_hardening_utils.py`
- `tests/conftest.py`
- `tests/pytest_activity_parser_charts.py`
- `tests/pytest_backend_implementations.py`
- `tests/pytest_hardening_api.py`
- `tests/pytest_hardening_parser.py`
- `tests/pytest_hardening_workout_engines.py`
- `tests/pytest_multitenant_stress.py`
- `tests/pytest_security_hardening.py`
- `tests/pytest_workout_engines.py`
- `tools/stress/deep_bottleneck.py`
- `tools/stress/multitenant_stress.py`

## File modificati

- `.env.example`
- `CHANGELOG.md`
- `Makefile`
- `api_app.py`
- `engines/io/activity_charts.py`
- `engines/io/fit_parser.py`
- `engines/io/workout_summary.py`
- `engines/performance/race_prediction_engine.py`
- `engines/recovery/hrv_engine.py`
- `pyproject.toml`
- `tests/pytest_corrupt_fit.py`
