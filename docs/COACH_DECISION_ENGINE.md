# Coach decision engine

Coach decision-support modules for strength, fueling, safety, attention, adherence, testing, race execution, periodization, communication drafts and environment adjustments.
**Not** mental-health diagnosis, meal plans or autonomous coaching.

## Endpoints

| Method | Path | Schema |
|--------|------|--------|
| POST | `/coach/strength/prescription` | `strength_prescription.v1` |
| POST | `/coach/nutrition/performance-targets` | `performance_fueling_targets.v1` |
| POST | `/coach/checkin` | `athlete_checkin.v1` |
| POST | `/coach/decision-safety` | `decision_safety.v1` |
| POST | `/coach/attention` | `coach_attention.v1` |
| POST | `/coach/attention/roster` | `coach_attention.v1` |
| POST | `/coach/adherence` | `adherence_report.v1` |
| POST | `/coach/testing-plan` | `testing_plan.v1` |
| POST | `/coach/race-execution` | `race_execution_plan.v1` |
| POST | `/coach/periodization` | `periodization_review.v1` |
| POST | `/coach/communication-draft` | `communication_draft.v1` |
| POST | `/coach/environment-adjustment` | `environment_adjustment.v1` |

## TwinState keys

- `strength_state`, `nutrition_performance_state`
- `checkin_state`, `decision_safety_state`, `coach_attention_state`
- `adherence_state`, `testing_plan_state`, `race_execution_state`
- `periodization_state`, `communication_draft_state`, `environment_state`

## Principles

1. **Human review flags** — `psychological_support_flag` recommends coach conversation; never diagnoses.
2. **Intensity gate** — `ok_to_auto_suggest` | `do_not_auto_progress` | `do_not_prescribe_intensity`.
3. **Attention triage** — ranks athletes for daily coach workflow.
4. **Adherence** — planned vs done with reason candidates, not just a score.
5. **Testing scheduler** — recommends calibration tests when model confidence is weak.
6. **Race execution** — pacing, fueling targets and failure modes for coach review.
7. **Periodization** — macro coherence, load-risk and gym/bike conflict hints.
8. **Communication draft** — editable message text; `coach_review_required` and `not_autonomous`.
9. **Environment** — heat, humidity and altitude caps for session planning.

## Engines

- `engines/strength/strength_prescription_engine.py`
- `engines/nutrition/performance_fueling_engine.py`
- `engines/coach/prescription_safety.py`
- `engines/coach/checkin_engine.py`
- `engines/coach/decision_safety_engine.py`
- `engines/coach/attention_engine.py`
- `engines/coach/adherence_engine.py`
- `engines/coach/testing_scheduler_engine.py`
- `engines/coach/race_execution_engine.py`
- `engines/coach/periodization_engine.py`
- `engines/coach/communication_draft_engine.py`
- `engines/coach/environment_adjustment_engine.py`
