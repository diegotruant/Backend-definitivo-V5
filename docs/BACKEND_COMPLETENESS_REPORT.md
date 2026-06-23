# Backend Completeness Report — V5.2

**OpenAPI:** 105 paths (see `docs/API_ENDPOINT_INDEX.md`). **Version:** 5.2.1.

## General status

The backend is ready as a development foundation for an advanced frontend product. It is stateless, modular, and built around physiological engines separated from the API.

This delivery does not include a database, authentication, or a job queue: those are intentionally left to the application/production layer. The backend returns JSON-serializable data that the frontend/DB must save and send back.

## Main modules

| Area | Status | Notes |
|---|---|---|
| FastAPI API | Ready | `api_app.py` |
| FIT ingest | Ready | parsing and power curve |
| MMP / power curve | Ready | persistable curve updates |
| Metabolic snapshot | Ready | VO2max, VLamax, MLSS, FatMax, MAP |
| Expressiveness gate | Ready | avoids unreliable values |
| Workout summary | Ready | modular activity report |
| Mader durability | Ready | mechanistic durability |
| In-person testing | Ready | tablet envelope |
| Lab/lactate validation | Present | to use in validated tests |
| Anchor profile flow | Ready | proposal → coach confirmation → anchor |
| Kalman / Bayesian / lab / explainability / race APIs | Ready (HTTP) | V5.2.0 engine coverage |
| Dual metabolic + Coggan zones on rides | Ready | V5.2.1 — coach chooses system |
| Team Learning Engine | Added | residual learning team/athlete/phenotype |
| Frontend MVP | Present but not final | needs rebuild according to the blueprint |

## Available endpoints

| Endpoint | Status | Frontend usage |
|---|---|---|
| `GET /health` | Ready | service monitoring |
| `POST /test/propose` | Ready | upload FIT test |
| `POST /test/confirm` | Ready | coach and anchor confirmation |
| `POST /ride/ingest` | Ready | import activities and MMP curve |
| `POST /ride/update-profile` | Ready | update profile from ride |
| `POST /profile/snapshot` | Ready | metabolic profile dashboard |
| `POST /ride/summary` | Ready | activity report |
| `POST /ride/durability` | Ready | durability from snapshot |
| `POST /test/in-person` | Ready | tablet/lactate/Mader test |
| `POST /team/calibration/update` | Added | update team learning model |
| `POST /team/calibration/apply` | Added | apply calibration to value/snapshot |

## What’s missing for production

These points are not backend bugs, but responsibilities of the product layer:

1. Authentication and roles.
2. Persistent database.
3. FIT file storage.
4. Job queue for parsing and heavy calculations.
5. Audit log of access and models.
6. GDPR and consent management.
7. Model versioning in the DB.
8. Error monitoring.
9. Rate limiting.
10. Backup and disaster recovery.

## What the database must store

Minimum required:

- team;
- athletes;
- activity files;
- curve MMP;
- physiological anchors;
- metabolic snapshots;
- workout summary;
- validation events;
- team calibration model;
- model version.

## Recommended tests to run

```bash
PYTHONPATH=. pytest -q tests/pytest_smoke.py tests/test_team_learning_engine.py
```

Expected result:

```text
6 passed
```

## Technical positioning

The backend should not be presented as generic AI. It should be presented as:

> Physics/physiology-informed performance engine with audited residual learning.

Example phrasing:

> A physiology-based performance engine, validated by tests and with auditable residual learning.
