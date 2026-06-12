# Backend implementations V2 — TwinState, projection, neuromuscular, source normalization

This package adds the backend features requested before building a full product frontend.

## 1. Canonical TwinState v1

New package: `engines/twin_state/`

The canonical object is a single JSON blob with `schema_version = twin_state.v1` and the sections a frontend/database should persist and replay:

- athlete profile
- measured anchor
- metabolic snapshot and normalized metabolic metrics
- rolling power curve
- load/readiness state
- sensor quality
- power source state
- workout calendar state
- compliance history
- team calibration state
- state confidence
- warnings and event log
- scope declarations

Endpoints:

- `POST /twin/state/build`
- `POST /twin/state/update-from-ride`
- `POST /twin/state/update-from-workout-result`

## 2. Seasonal what-if projection

New package: `engines/projection/`

Endpoint:

- `POST /twin/state/project`
- `POST /projection/season` alias

Input: current TwinState + future calendar/workout plan.

Output: daily projected CP, W′, VO2max, VLaMax, CTL/ATL/form/readiness, final delta, assumptions and warnings.

V1 is bounded and conservative. It is a coach-facing what-if simulator, not a lab-grade adaptation oracle.

## 3. Neuromuscular sprint profile

New file: `engines/performance/neuromuscular_profile.py`

Endpoint:

- `POST /performance/neuromuscular-profile`

Extracts:

- Pmax
- W/kg Pmax
- best 1s/5s/10s/15s/30s
- cadence at Pmax
- torque proxy at Pmax
- repeat sprint candidates
- repeatability score
- fatigue index
- L/R balance at Pmax when available
- sprint phenotype and recommendations

## 4. Power-source offset / drift guard

New file: `engines/io/power_source_normalizer.py`

Endpoint:

- `POST /power-source/normalize`

Detects systematic offsets between sources such as indoor trainer vs outdoor power meter using overlapping MMP signatures. It returns baseline source, pairwise offsets, normalization factors and warnings when CP/MMP could be contaminated by mixed sources.

## 5. Manual non-cycling load injection

New package: `engines/load/`

Endpoint:

- `POST /load/manual`

Converts manual RPE × duration sessions into approximate load/recovery/readiness modifiers. This declares the non-cycling scope explicitly without pretending to have cycling-power precision for gym/running/life stress.

## Tests

Added:

- `tests/pytest_backend_implementations.py`

Validation run:

- targeted new tests: `6 passed`
- smoke/workout/chart/new: `14 passed`
- hardening: `12 passed, 1 skipped`
- full collected suite: `39 passed, 12 skipped`

Skips are existing environment-dependent FIT tests when optional real FIT/dependency conditions are unavailable.
