# Coach decision engine

Coach decision-support modules for strength, fueling, safety, attention, adherence, testing, race execution, periodization, communication, environment, PNEI context, endocrine context, constraints and training safety.
**Not** mental-health diagnosis, meal plans, hormone therapy or autonomous coaching.

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
| POST | `/coach/pnei-context` | `pnei_context.v1` |
| POST | `/coach/endocrine-context` | `endocrine_context.v1` |
| POST | `/coach/constraints` | `constraints_adaptation.v1` |
| POST | `/coach/training-safety` | `training_safety.v1` |

## TwinState keys

- `strength_state`, `nutrition_performance_state`
- `checkin_state`, `decision_safety_state`, `coach_attention_state`
- `adherence_state`, `testing_plan_state`, `race_execution_state`
- `periodization_state`, `communication_draft_state`, `environment_state`
- `pnei_state`, `endocrine_context_state`, `training_safety_state`, `constraints_state`

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
10. **PNEI context** — systemic strain from proxy signals (`RISK_MODEL`), not diagnosis.
11. **Endocrine context** — energy availability and recovery risk; optional biomarkers with professional interpretation.
12. **Training safety** — injury/illness prudence layer.
13. **Constraints** — lifestyle adaptation for real athletes.

## Context layers

`decision_safety` considers `pnei_state`, `endocrine_context_state` and `training_safety_state` from TwinState.

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
- `engines/coach/pnei_context_engine.py`
- `engines/endocrine/endocrine_context_engine.py`
- `engines/coach/constraints_engine.py`
- `engines/coach/injury_illness_engine.py`
