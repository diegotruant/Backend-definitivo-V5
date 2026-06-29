# Coach decision engine — phase 2

Subjective check-in, unified decision safety and coach attention prioritization.
**Not** mental-health diagnosis or autonomous coaching.

## Endpoints

| Method | Path | Schema |
|--------|------|--------|
| POST | `/coach/checkin` | `athlete_checkin.v1` |
| POST | `/coach/decision-safety` | `decision_safety.v1` |
| POST | `/coach/attention` | `coach_attention.v1` |
| POST | `/coach/attention/roster` | `coach_attention.v1` |

Phase 1 endpoints remain: `/coach/strength/prescription`, `/coach/nutrition/performance-targets`.

## Principles

1. **Human review flags** — `psychological_support_flag` recommends coach conversation; never diagnoses.
2. **Intensity gate** — `ok_to_auto_suggest` | `do_not_auto_progress` | `do_not_prescribe_intensity`.
3. **Attention triage** — ranks athletes for daily coach workflow.
4. **TwinState** — `checkin_state`, `decision_safety_state`, `coach_attention_state`.

## Psychological support (example)

```json
{
  "status": "human_check_recommended",
  "human_check_recommended": true,
  "reason": "motivation_low_for_5_days",
  "safe_action": "Coach conversation recommended. Do not escalate training load automatically.",
  "not_a_diagnosis": true
}
```

## Decision safety levels

| Level | `intensity_gate` |
|-------|------------------|
| `ok_to_auto_suggest` | Model may suggest |
| `coach_review_recommended` | `do_not_auto_progress` |
| `professional_review_recommended` | `do_not_prescribe_intensity` |

## Engines

- `engines/coach/checkin_engine.py`
- `engines/coach/decision_safety_engine.py`
- `engines/coach/attention_engine.py`
- `engines/coach/prescription_safety.py` (shared, phase 1)
