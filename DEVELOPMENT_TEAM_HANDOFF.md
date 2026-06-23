# Development handoff — Physiological Digital Twin Cycling Backend V5

## Goal of this handoff

This repository contains the backend for a performance intelligence platform for elite cycling. The frontend team should not need to know cycling: it must build an interface that correctly displays data, respects model confidence, and guides coaches and performance scientists in decision-making.

The product must not look like a clone of a social activity platform, consumer platform, or coaching platform. It must look like a **physiological digital twin**: a system that combines real data, metabolic models, validated tests, and athlete/team learning.

## What is already ready in the backend

- Stateless FastAPI API — **105 OpenAPI paths** (`docs/API_ENDPOINT_INDEX.md`).
- FIT parsing and activity ingestion.
- Metabolic profile from MMP (snapshot + extended profile/lab/kalman HTTP APIs).
- Dual zone systems on activities: **metabolic MLSS** + **Coggan FTP** (coach choice).
- Workout summary, mechanistic durability, HRV / cardiac / thermal when data present.
- In-person tests, lactate/Mader validation, glycolytic vLaPeak validation.
- Team Learning Engine, TwinState, season projection, explainability narratives.

## Key files for the frontend

| File | Purpose |
|---|---|
| `openapi/openapi.json` | Committed HTTP contract (105 paths) |
| `docs/API_ENDPOINT_INDEX.md` | Endpoint inventory by tag |
| `docs/FRONTEND_DEVELOPER_GUIDE.md` | Extended technical guide (v5.2.1) |
| `frontend/src/api/client.ts` | Typed client for all endpoints |
| `docs/FRONTEND_IMPLEMENTATION_BLUEPRINT.md` | Main frontend specification |
| `docs/API_PAYLOAD_EXAMPLES.md` | Payload/response examples |
| `docs/COACH_UX_COPYBOOK.md` | Coach-facing copy and badges |
| `frontend/src/contracts.ts` | Domain TypeScript interfaces |

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
make test
make test-all
make check
make typecheck-metabolic
```
