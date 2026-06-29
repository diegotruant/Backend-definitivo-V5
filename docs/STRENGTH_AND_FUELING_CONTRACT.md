# Strength prescription and performance fueling contract

Backend-owned coach prescriptions for gym strength and **performance fueling targets**.
This is **not** a meal plan, diet app or mental-health module.

## Endpoints

| Method | Path | Schema |
|--------|------|--------|
| POST | `/coach/strength/prescription` | `strength_prescription.v1` |
| POST | `/coach/nutrition/performance-targets` | `performance_fueling_targets.v1` |

## Design principles

1. **Physiology first** — classify need from TwinState (metabolic snapshot, load, readiness), not from a generic exercise list.
2. **Cycling-specific** — every prescription includes `bike_conflict_rules` and interference risk.
3. **Safety gate** — shared `decision_safety` via `engines/coach/prescription_safety.py`.
4. **Not a diet** — nutrition output uses availability targets (`carbohydrate_availability`, `protein_recovery_priority`) only.
5. **TwinState persistence** — `strength_state` and `nutrition_performance_state` on build.

## Strength output (summary)

```json
{
  "schema_version": "strength_prescription.v1",
  "measurement_tier": "PRESCRIPTION_MODEL",
  "primary_need": "max_strength",
  "primary_goal": "max_strength_neural",
  "weekly_frequency": 2,
  "interference_risk": "moderate",
  "sessions": [],
  "bike_conflict_rules": {},
  "decision_safety": {},
  "limitations": []
}
```

### Primary need values

- `max_strength`
- `low_cadence_torque`
- `muscular_endurance`
- `structural_stability`
- `neuromuscular_power`
- `maintenance`

## Fueling output (summary)

```json
{
  "schema_version": "performance_fueling_targets.v1",
  "not_a_diet": true,
  "targets": {
    "carbohydrate_availability": "moderate",
    "protein_recovery_priority": "high",
    "glycogen_risk": "low",
    "hydration_priority": "normal"
  },
  "estimated_demands": {
    "session_carbohydrate_g": 142.0,
    "session_fat_g": 38.0,
    "estimated_recovery_hours": 18.5,
    "recovery_estimation_method": "empirical_formula"
  },
  "red_flags": [],
  "limitations": []
}
```

## Safety statuses

| Status | Meaning |
|--------|---------|
| `ok` | Model may suggest prescription |
| `caution` | Reduce volume; coach check-in |
| `requires_professional_review` | Injury/medical flags — mobility only |

## TwinState keys

| Key | Source |
|-----|--------|
| `strength_state` | `strength_prescription` response |
| `nutrition_performance_state` | `performance_fueling_targets` response |

## Linked engines

- `engines/strength/strength_prescription_engine.py`
- `engines/nutrition/performance_fueling_engine.py`
- `engines/coach/prescription_safety.py`
- `engines/metabolic/metabolic_coach_curves.py` (CHO demand / recovery inputs)
