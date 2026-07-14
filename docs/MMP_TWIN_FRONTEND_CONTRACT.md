# MMP, TwinState, Supabase and frontend contract

Status: **contract freeze / implementation guidance**  
Backend baseline: **5.2.6**  
Current document impact: **NONE** — documentation only  
Future `mmp_state.v1` implementation impact: **ADDITIVE**

## 1. Purpose

This document defines the single source of truth and the allowed data flow for the athlete's longitudinal Mean Maximal Power (MMP) curve.

It exists to prevent the backend, Supabase and frontend from independently inventing different meanings for:

- the rolling MMP curve;
- MMP quality and completeness;
- whether the curve may be displayed;
- whether the metabolic profile may be calculated or refreshed;
- what happens when data expires or becomes unreliable.

The backend remains stateless. Supabase persists the canonical `twin_state.v1` document and the frontend reads that persisted document.

## 2. Current contract frozen at backend 5.2.6

### 2.1 Canonical source of truth

The current longitudinal curve is stored only at:

```text
twin_states.twin_state.rolling_power_curve
```

`rolling_power_curve` is part of the canonical `twin_state.v1` document.

Other curve copies may exist for audit or convenience, but they are not the canonical current state:

| Location | Meaning | Source of truth? |
|---|---|---:|
| `twin_states.twin_state.rolling_power_curve` | Current rolling athlete MMP with provenance | **Yes** |
| `/ride/ingest.curve` | Candidate updated curve returned by one ingest operation | No; persist into TwinState first |
| `/ride/ingest.mmp_for_profiler` | Simplified `{duration_s: power_w}` view for the profiler | No |
| `activities.mmp_for_profiler` | Optional per-activity audit/debug material | No |
| `athletes.latest_curve` | Legacy or denormalized mirror | No |
| activity summary MMP | Best efforts from one activity | No |

The frontend must not merge activity MMP values by itself. Curve aggregation is backend responsibility.

### 2.2 Current `rolling_power_curve` shape

The existing field remains a map keyed by duration in seconds:

```json
{
  "5": {
    "duration_s": 5,
    "power_w": 986.4,
    "ride_id": "activity-123",
    "ride_date": "2026-07-10",
    "reliability": 0.97
  },
  "300": {
    "duration_s": 300,
    "power_w": 402.1,
    "ride_id": "activity-108",
    "ride_date": "2026-06-28",
    "reliability": 0.93
  }
}
```

Frozen field meanings:

| Field | Type | Meaning |
|---|---|---|
| map key | string seconds | Same duration as `duration_s`; JSON object keys are strings |
| `duration_s` | integer | Effort duration in seconds |
| `power_w` | number | Best accepted mean power for that duration |
| `ride_id` | string | Activity that supplied the winning value |
| `ride_date` | ISO date | Date of the winning effort |
| `reliability` | number 0–1 | Reliability inherited from activity data quality |

These fields must not be renamed, removed or have their type changed without a **BREAKING** frontend contract review.

### 2.3 Current `/ride/ingest` output

The current response is an operation result, not a persistent athlete document:

```json
{
  "curve": {},
  "mmp_for_profiler": {},
  "improvements": 4,
  "ride_usable": true,
  "profile_should_refresh": true,
  "notes": [],
  "file_hash": "...",
  "parser_version": "...",
  "data_quality_score": 0.94,
  "available_signals": ["power", "heart_rate"],
  "laps": []
}
```

Rules:

1. `curve` is persisted through `/twin/state/update-from-ride` into `TwinState.rolling_power_curve`.
2. `mmp_for_profiler` is a computational projection of the same curve, not a second database authority.
3. `profile_should_refresh` means a profile-critical duration changed or expired.
4. `profile_should_refresh` does **not** by itself prove that the MMP is scientifically complete enough to publish.
5. `ride_usable = false` means the incoming ride must not contribute new anchors.

### 2.4 Rolling window and provenance

The backend uses a rolling time window, currently 90 days by default. Old winning efforts may expire.

The persisted curve therefore represents current fitness, not permanent personal records.

The frontend must use `ride_date` as provenance and may display anchor age. It must not silently label the curve as an all-time power record.

## 3. Existing scientific quality information

The existing MMP quality engine returns:

```json
{
  "total_anchors": 17,
  "total_source_files": 8,
  "issues": [],
  "issue_counts_by_category": {},
  "quality_score": 0.9,
  "classification": "good",
  "recommendations": [],
  "tier": "HEURISTIC"
}
```

Existing classifications are frozen as:

```text
good | fair | poor
```

Existing issue categories include:

```text
identical_plateau
rolling_window_redundant
sprint_outlier
flat_long_region
non_monotonic
```

These values describe data quality. They are not yet a frontend visibility lifecycle.

## 4. Coverage bands

The UI and future publication gate must reason in physiological duration bands rather than activity count alone.

| Band | Duration range | Profile role |
|---|---:|---|
| Sprint | 5–15 s | Neuromuscular / peak power |
| Glycolytic | 20–60 s | Anaerobic / VLamax-related information |
| VO2 | 180–720 s | Aerobic power / MAP region |
| Threshold | 1200–3600 s | MLSS / CP / sustainable power region |

A fixed number of activities must never be treated as sufficient by itself. Ten uninformative endurance rides are not equivalent to a well-covered MMP curve.

Activity count is supporting evidence; coverage, provenance, freshness, reliability and curve integrity decide publication eligibility.

## 5. Future additive field: `mmp_state.v1`

The next implementation phase may add the following sibling field to `twin_state.v1`:

```text
twin_states.twin_state.mmp_state
```

`rolling_power_curve` remains unchanged. The curve is not moved inside `mmp_state`.

Proposed additive shape:

```json
{
  "schema_version": "mmp_state.v1",
  "lifecycle_status": "collecting",
  "frontend_visibility": "progress_only",
  "profile_eligible": false,
  "profile_stale": false,
  "quality": {
    "score": 0.68,
    "classification": "fair",
    "issue_counts_by_category": {},
    "blocking_issues": []
  },
  "coverage": {
    "sprint": "present",
    "glycolytic": "missing",
    "vo2": "partial",
    "threshold": "missing",
    "missing_bands": ["glycolytic", "threshold"]
  },
  "anchor_count": 9,
  "source_activity_count": 5,
  "critical_durations_present": [5, 15, 180, 300],
  "updated_at": "2026-07-14T08:00:00Z",
  "decision_reasons": [
    "Threshold duration band is missing."
  ],
  "warnings": []
}
```

### 5.1 Lifecycle values

The proposed enum is:

```text
collecting | provisional | published | degraded | invalid
```

| State | Meaning | Curve display | Metabolic profile use |
|---|---|---|---|
| `collecting` | Data exists but coverage is insufficient | Hide curve; show collection progress only | No |
| `provisional` | Curve is plausible but not publication-grade | Coach-only preview with explicit provisional banner | No automatic refresh |
| `published` | Quality and coverage gates passed | Full curve and provenance may be shown | Yes |
| `degraded` | Previously publishable state lost freshness, coverage or reliability | Show warning; do not present as current/fully reliable | No new automatic refresh until recovered |
| `invalid` | Blocking integrity error, such as unresolved non-monotonic data | Hide curve and derived profile claims | No |

Adding `mmp_state` and these enum values is an **ADDITIVE frontend change** and must be coordinated before implementation.

### 5.2 Visibility values

The proposed visibility enum is:

```text
hidden | progress_only | coach_preview | show
```

The frontend must use `frontend_visibility`; it must not infer visibility from anchor count.

### 5.3 Publication gate principles

Exact numeric thresholds belong to the scientific implementation and tests, not to frontend code.

At minimum, publication evaluation must consider:

- MMP monotonicity;
- blocking quality issues;
- required physiological bands;
- anchor freshness within the rolling window;
- number of independent source activities;
- reliability of the winning anchors;
- sufficient threshold and VO2 information for the metabolic profiler;
- whether missing signals cause an expected degraded result.

The frontend must never reproduce these rules.

## 6. Supabase persistence contract

### 6.1 Canonical row

Recommended canonical storage:

```text
table: twin_states
key: athlete_id
jsonb: twin_state
schema inside JSON: twin_state.v1
```

The update after a FIT must be transactional with the activity status where possible:

```text
load current TwinState
→ ingest FIT using stored rolling_power_curve
→ update TwinState
→ optionally refresh metabolic profile if eligible
→ save activity + TwinState
```

### 6.2 Idempotency

The same activity must not improve or load the athlete twice.

Use the existing identity principle:

```text
unique athlete_id + file_hash
```

Reprocessing may replace the activity result, but must not duplicate load or create duplicate curve provenance.

### 6.3 Denormalized columns

Indexes or summary columns may mirror selected values for dashboard performance, but the JSON contract remains authoritative.

Any mirror must be treated as rebuildable from `twin_state`.

## 7. Frontend rendering contract

### 7.1 Current baseline before `mmp_state` exists

Until the additive implementation is released:

- read the curve from `twin_state.rolling_power_curve`;
- label it as a rolling MMP / current power-duration curve;
- display provenance and anchor date when available;
- do not infer scientific publication readiness from the number of points;
- do not calculate or merge MMP values in TypeScript;
- use backend `metabolic_snapshot` masking, status, warnings and confidence for metabolic KPIs.

### 7.2 After `mmp_state.v1` is implemented

| Lifecycle | Recommended UI |
|---|---|
| `collecting` | “Data collection in progress”; missing-band checklist; no curve |
| `provisional` | Coach-only chart; “Provisional curve — not used for profile” |
| `published` | Full MMP chart, W/Wkg toggle, provenance, updated date |
| `degraded` | Warning banner; explain stale/missing band; avoid current-profile claims |
| `invalid` | Data Quality error panel; no curve or derived profile KPIs |

The frontend must treat unknown future lifecycle values as non-published and hide derived claims safely.

### 7.3 Profile refresh rule

The worker/backend orchestration decides whether a profile refresh is allowed.

The frontend must not call `/ride/update-profile` solely because:

```json
{ "profile_should_refresh": true }
```

After `mmp_state.v1` exists, the condition becomes conceptually:

```text
profile_should_refresh == true
AND mmp_state.profile_eligible == true
AND lifecycle_status == published
```

## 8. Degradation and missing signals

Expected safe degradation:

| Missing or bad input | Expected result |
|---|---|
| No usable power | Ride does not contribute; existing curve remains |
| Poor activity quality | `ride_usable=false`; no new anchors |
| Missing weight | Curve may update, but W/kg plausibility is weaker and warning is retained |
| Missing HR/cadence | Power MMP may still update; confidence/quality context is reduced |
| Missing duration bands | Curve remains collecting/provisional; profile is not automatically published |
| Expired critical anchors | Profile refresh/stale evaluation is required; state may become degraded |
| Non-monotonic curve | Blocking integrity issue; state becomes invalid until corrected |

No missing signal may be replaced with invented frontend data.

## 9. Change classification

### This documentation PR

```text
FRONTEND IMPACT: NONE
Endpoints affected: none
Request schema changes: none
Response schema changes: none
Generated OpenAPI changed: no
Generated TypeScript client changed: no
Frontend action required: read/review contract only
Supabase action required: none
```

### Future `mmp_state.v1` implementation

```text
FRONTEND IMPACT: ADDITIVE
Endpoints affected: TwinState build/update responses
Request schema changes: optional mmp_state accepted in TwinState
Response schema changes: optional mmp_state added
Generated OpenAPI changed: yes
Generated TypeScript client changed: yes
Frontend action required: implement lifecycle rendering and safe unknown-state fallback
Supabase action required: persist new optional field inside twin_state JSONB; no table migration required if JSONB remains canonical
```

### Changes that would be breaking

The following are forbidden without explicit frontend coordination:

- replacing `rolling_power_curve` with an envelope object;
- moving the curve inside `mmp_state`;
- renaming `power_w`, `duration_s`, `ride_id`, `ride_date` or `reliability`;
- changing duration keys from seconds;
- removing the existing ingest fields;
- allowing frontend code to become the MMP aggregator.

## 10. Implementation order after contract approval

1. Add characterization tests for the current curve and ingest payload.
2. Add backend-only scientific publication evaluation.
3. Add optional `mmp_state.v1` to TwinState models and update engine.
4. Regenerate OpenAPI and TypeScript.
5. Notify frontend with the exact additive payload and UI rules.
6. Add frontend lifecycle handling.
7. Only then enable published/degraded profile orchestration.

No runtime change should be merged before steps 1–2 are green and the frontend impact is recorded.
