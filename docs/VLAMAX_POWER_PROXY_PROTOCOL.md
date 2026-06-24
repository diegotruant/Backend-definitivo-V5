# VLamax power proxy protocol — fixed T_PCr semantics

This document defines how the backend interprets sprint power traces for the power-derived VLamax proxy (`cLaMax_P`). It is the coach-facing and developer-facing reference for `engines/metabolic/power_vlamax_estimator.py` and related glycolytic-profile outputs.

## Core principle

The backend does **not** use the time of mechanical peak power (`t_Ppeak`) as the start of the glycolytic calculation window.

Instead, the backend uses a fixed alactic / PCr-dominant phase duration:

```text
T_PCr = 3.5 s
```

The glycolytic window starts after this fixed T_PCr, with a small oxidative contribution subtracted separately.

## Why fixed T_PCr is used

Using `t_Ppeak` as `t_PCr` can bias the estimate when the athlete reaches peak power late. This is common in:

- amateur athletes not accustomed to maximal sprinting;
- indoor trainers with inertia or ERG/level-mode quirks;
- suboptimal gear choice;
- seated starts or cautious pacing;
- poor neuromuscular coordination during the first seconds.

A late mechanical power peak is therefore treated as a **protocol-quality note**, not as proof that glycolysis starts later.

## Backend behavior

The estimator returns:

- `features.t_pcr_s = 3.5`
- `features.t_p_peak_s = observed mechanical peak time`
- `quality_flags = ["late_power_peak_protocol_note"]` when `t_p_peak_s > 3.5`
- `quality_flags = ["very_late_power_peak_protocol_note"]` when `t_p_peak_s > 6.0`

Late-peak flags are **not physiological error flags**. They are intended for the coach UI.

Confidence is not penalized for a normal late peak. A very late peak receives only a mild penalty, because it may still indicate protocol or execution issues.

## What the coach UI should say

Suggested copy:

> Peak power was reached after the fixed PCr window. This is common in athletes who are not sprint specialists and does not automatically invalidate the VLamax power proxy. Treat it as a protocol note; repeat the sprint only if the glycolytic estimate is important for the coaching decision.

## Required distinction in every UI

Never conflate these three values:

| Field | Meaning | UI badge |
| --- | --- | --- |
| `estimated_vlamax_mmol_L_s` | Mader/MMP model parameter | Model estimate |
| `power_derived_vlamax` | Sprint power trace proxy | Power proxy |
| `observed_vlapeak_mmol_l_s` | Blood lactate pre/post sprint | Lab observed |

`power_derived_vlamax` is not a lab measurement. `observed_vlapeak_mmol_l_s` is not automatically identical to Mader VLamax. They are related anchors that should be compared with confidence, protocol notes and limitations.

## Regression test

The repository includes a regression test for an amateur-style sprint where peak power is reached after 3.5 s. Expected behavior:

- estimator returns `status = success`;
- `t_pcr_s` stays fixed at 3.5 s;
- `t_p_peak_s` reflects the observed late mechanical peak;
- `late_power_peak_protocol_note` is present;
- confidence remains high when the sprint is otherwise sustained and anchored.

## Implementation reference

- `engines/metabolic/power_vlamax_estimator.py`
- `tests/pytest_power_vlamax_estimator.py`
- `docs/RELEASE_NOTES_v5.2.2.md`
