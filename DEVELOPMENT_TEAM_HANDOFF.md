# Development handoff — Physiological Digital Twin Cycling Backend V5

## Goal of this handoff

This repository contains the backend for a performance intelligence platform for elite cycling. The frontend team should not need to know cycling: it must build an interface that correctly displays data, respects model confidence, and guides coaches and performance scientists in decision-making.

The product must not look like a clone of a social activity platform, consumer platform, or coaching platform. It must look like a **physiological digital twin**: a system that combines real data, metabolic models, validated tests, and athlete/team learning.

## What is already ready in the backend

- Stateless FastAPI API in `api_app.py`.
- FIT parsing and activity ingestion.
- Power curve / MMP.
- Metabolic profile from MMP.
- Estimation of VO2max, VLamax, MLSS, FatMax, MAP.
- Expressiveness gate: the system knows when data is insufficient.
- Workout summary.
- Mechanistic durability.
- HRV / cardiac response when data is present.
- In-person tests via JSON envelope.
- Lactate / Mader validation.
- Physiological anchor confirmed by the coach.
- Team Learning Engine: residual learning from validated tests.

## Key files for the frontend

| File | Purpose |
|---|---|
| `api_app.py` | API contracts currently available |
| `docs/FRONTEND_IMPLEMENTATION_BLUEPRINT.md` | Main frontend specification |
| `docs/API_PAYLOAD_EXAMPLES.md` | Payload/response examples for each endpoint |
| `docs/COACH_UX_COPYBOOK.md` | Texts, badges, and traffic lights to show coaches |
| `docs/TEAM_LEARNING_ENGINE.md` | Explanation of the self-learning engine |
| `docs/FRONTEND_DEVELOPER_GUIDE.md` | Existing extended technical guide |
| `frontend/src/contracts.ts` | Base TypeScript interfaces to start from |
| `frontend/src/metricDictionary.ts` | UI metric dictionary |
| `frontend/src/api.ts` | Minimal API client |
| `frontend/src/mockData.ts` | Mock data to prototype pages without a live backend |

## Non-negotiable UI principle

Every number must tell the user whether it is:

1. measured directly;
2. calculated with a standard formula;
3. estimated by a physiological model;
4. learned/corrected by validated tests;
5. unreliable or unavailable.

Never show a `null`, `skipped`, or masked value as if it were a certain value.

## The 7 pages to build

1. **Team Command Center** — team view, model accuracy, athlete status.
2. **Athlete Digital Twin** — complete metabolic profile of the single athlete.
3. **Activity Analysis** — single ride/workout analysis.
4. **Testing Lab** — FIT/tablet/lactate test upload and coach confirmation.
5. **Model Accuracy & Learning** — team self-learning dashboard.
6. **Coach Planner** — operational targets, zones, recommendations.
7. **Data Quality Center** — data completeness, warnings, missing sensors.

## What must be memorable for a WT team

The platform must communicate three messages:

1. **It does not only look at how strong the athlete is when fresh, but how strong they remain after hours of fatigue.**
2. **It does not provide magic numbers: it measures its own error against Mader/lactate/lab tests.**
3. **The more the team uses and validates it, the more the model calibrates on the team cohort.**

## Implementation rule

The backend is stateless. The frontend/database must save and send back:

- `curve` for each athlete;
- `anchor` for each athlete;
- latest `metabolic_snapshot`;
- `calibration_model` for the team;
- `ValidationEvent` for each validated test;
- `model_version` associated with each prediction.

## Quick backend command

```bash
pip install -r requirements-dev.txt
uvicorn api_app:app --reload
```

Health check:

```bash
curl http://localhost:8000/health
```

## Quick tests

```bash
PYTHONPATH=. pytest -q tests/pytest_smoke.py tests/test_team_learning_engine.py
```
