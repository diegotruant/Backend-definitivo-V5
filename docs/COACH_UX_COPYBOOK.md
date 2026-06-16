# Coach UX Copybook — How to Explain the Numbers Without Knowing Cycling

This file contains ready-to-use copy for UI, tooltips, badges, empty states, and warnings.

## 1. Language rule

Never use “measured” if the backend produced a modeled estimate.

Use:

- “estimated by the model”;
- “calibrated on team tests”;
- “validated by test”;
- “insufficient data”;
- “requires targeted test”.

## 2. Badges

### Measured

Badge text: `Measured`

Tooltip:

> Value obtained directly from a test or sensor, not estimated by the model.

### Model estimate

Badge text: `Model estimate`

Tooltip:

> Value estimated by the physiological model using power, athlete profile, and MMP curve. Interpret together with confidence.

### Team calibrated

Badge text: `Team calibrated`

Tooltip:

> The estimate was corrected using historical errors observed in the team’s validated tests.

### Low confidence

Badge text: `Low confidence`

Tooltip:

> The available data does not cover all required physiological windows. Schedule a targeted test.

### Insufficient data

Badge text: `Insufficient data`

Tooltip:

> The backend does not have enough data to show this value responsibly.

## 3. Metric tooltips

### MLSS

> Estimated power at maximum sustainable metabolic stability. Useful for threshold work, time-trial pacing, and advanced endurance assessment.

### VO2max

> Estimated maximum aerobic capacity. Indicates the potential of the aerobic system. If it does not come from spirometry, it should be treated as an estimate.

### VLamax

> Indicator of glycolytic capacity. High values favor sprints and pace changes, but increase carbohydrate consumption. Requires reliable short/sprint data.

### FatMax

> Estimated power at which the athlete maximizes fat use. Useful for endurance and nutrition management, but less certain without direct metabolic data.

### Durability

> Ability to maintain performance after accumulated fatigue. Very important for long races and World Tour stages.

### Cardiac drift

> Increase in heart rate at the same power. May indicate fatigue, heat, dehydration, or insufficient aerobic base.

### MMP

> Athlete’s best mean power for different durations. It is the base curve used by the physiological model.

## 4. Traffic lights

### Green profile

> Coherent profile. Data covers the main windows and confidence is sufficient to use targets in training.

### Yellow profile

> Profile usable with caution. Some data windows are missing or confidence is moderate. Schedule a targeted test.

### Red profile

> Profile not reliable for important decisions. New data or validation with tests is needed.

## 5. Model Accuracy messages

### No validated tests

> The team does not yet have validated tests. The model uses only general physiology and cannot yet correct team-specific errors.

### Initial learning

> The system is starting to calibrate estimates. More validated tests are needed to reduce uncertainty.

### Active calibration

> The model uses the team’s historical errors to correct new estimates. Each correction is limited by conservative thresholds.

### Correction applied

> The final estimate includes a correction learned from validated tests. Open the audit to see base value, corrections, and expected margin.

## 6. Empty states

### Missing sprint data

> A maximal short effort is missing. VLamax and glycolytic capacity are less reliable. Schedule 10–30 second sprints under controlled conditions.

### Missing threshold data

> A 20–60 minute effort is missing. MLSS and FatMax may be masked or have low confidence.

### No HR

> Heart rate not available. Cardiac drift and aerobic decoupling cannot be calculated.

### No RR

> RR intervals not available. HRV and DFA-alpha1 cannot be calculated.

## 7. Safe commercial phrases

Use:

> The system progressively reduces estimate error thanks to the team’s validated tests.

> Every estimate shows confidence, data origin, and correction audit.

> The platform combines physiological model, real data, and longitudinal validation.

Do not use:

> The system no longer makes mistakes.

> The AI measures VO2max without a test.

> It replaces the lab.
