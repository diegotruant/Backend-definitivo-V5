# Scientific references for the Digital Twin backend

This document maps the mathematical and physiological engines in this backend
to the scientific literature referenced by the codebase or strongly implied by
the implemented algorithms.

Important scope note: these references document the scientific provenance of the
implemented methods. They are not, by themselves, external validation of this
backend against laboratory measurements. The repository currently states that
lab validation against gold-standard testing has not yet been completed.

## Reference status labels

- **Explicit**: author, year, model, or source is named in code comments,
  docstrings, README, or CHANGELOG.
- **Algorithmic**: the implemented algorithm is a standard method with a
  canonical publication, even if the exact citation is not written in code.
- **Contextual**: the reference supports interpretation or physiology around
  the implemented metric, but the backend uses a simplified or heuristic form.

## Module-to-literature map

| Area | Modules | Main concepts | Reference basis |
| --- | --- | --- | --- |
| Power profiling | `power_engine.py`, `coggan_classifier.py`, `zones_engine.py` | Normalized Power, IF, TSS, FTP estimate, power zones, rider phenotype tables | Allen & Coggan; Monod & Scherrer |
| Critical power and W' | `power_engine.py`, `w_prime_balance_engine.py`, `efforts_analyzer.py` | CP/W' fit, W' depletion and recovery | Monod & Scherrer; Skiba; Bartram |
| Mader metabolic model | `metabolic_profiler.py`, `bayesian_profiler.py`, `metabolic_kalman.py` | VO2max, VLamax, MLSS, FatMax, lactate production/removal | Mader & Heck; Mader; Nolte et al. |
| Bayesian inference | `bayesian_profiler.py` | Adaptive Metropolis-Hastings, Student-t likelihood, posterior uncertainty | Haario et al.; robust likelihood practice |
| Longitudinal tracking | `metabolic_kalman.py`, `neural_ode.py`, `lab_data.py` | Unscented Kalman Filter, lab anchoring, residual neural correction | Julier & Uhlmann; Wan & van der Merwe; Mujika; He et al. |
| Training load | `detraining_engine.py`, `training_variability_engine.py` | CTL, ATL, TSB, ACWR, monotony, strain | Banister; Foster; Gabbett; Hulin |
| HRV and thresholds | `hrv_engine.py`, `analysis.py`, `cardiac_engine.py` | DFA-alpha1, VT1/VT2 thresholds, RR cleaning, HR recovery | Peng; Gronwald; Rogers; Cole; Imai |
| Cardiac response | `cardiac_engine.py`, `thermal_engine.py` | Cardiac drift, Pa:Hr decoupling, HR kinetics, thermal drift | Friel; Coyle; Lambert; Rowell; Gonzalez-Alonso |
| Thermal physiology | `thermal_engine.py`, `fit_parser.py` | Core temperature, heat strain, heat acclimation, power loss in heat | Gonzalez-Alonso; Lorenzo; Periard; Rowell |
| Durability and fatigue resistance | `durability_engine.py`, `metabolic_flexibility_engine.py` | Durability index, NP drift, TTE sustainability, metabolic flexibility | Riis & Paton; Leo; Clark; San-Millan & Brooks; Jeukendrup |
| Interval classification | `interval_detector.py`, `mmp_quality.py` | HIIT/steady/test classification, anchor quality, MMP quality gates | Buchheit & Laursen; WKO-style MMP practice |

## 1. Power profiling, FTP, zones, and MMP

### Allen, H.; Coggan, A. (2010)

**Training and Racing with a Power Meter**. VeloPress.

- Status: **Explicit**
- Used for:
  - Normalized Power (30 s rolling mean, fourth power, fourth root).
  - Intensity Factor.
  - Training Stress Score.
  - FTP estimate from best 20 min power.
  - Power zones and rider power-profile tables.
- Main modules:
  - `power_engine.py`
  - `zones_engine.py`
  - `coggan_classifier.py`
  - `workout_summary.py`

### Monod, H.; Scherrer, J. (1965)

**The work capacity of a synergic muscular group**. Ergonomics.

- Status: **Explicit / Algorithmic**
- Used for:
  - Critical Power concept.
  - Linear work-time model: `work = CP * time + W'`.
- Main modules:
  - `power_engine.py`
  - `w_prime_balance_engine.py`
  - `efforts_analyzer.py`

### Buchheit, M.; Laursen, P. B. (2013)

High-intensity interval training prescription and classification framework.

- Status: **Explicit / Contextual**
- Used for:
  - HIIT work:rest interpretation.
  - Energy-system coverage windows for MMP expressiveness.
- Main modules:
  - `interval_detector.py`
  - `metabolic_profiler.py`

## 2. Mader model, MLSS, VO2max, VLamax, and FatMax

### Mader, A.; Heck, H. (1986)

Metabolic control theory and lactate kinetics in exercise physiology.

- Status: **Explicit**
- Used for:
  - Oxidative phosphorylation activation constant.
  - Glycolytic activation constant.
  - Lactate production/removal structure.
  - Reverse estimation of VO2max and VLamax from MMP.
- Main modules:
  - `metabolic_profiler.py`
  - `bayesian_profiler.py`
  - `metabolic_kalman.py`

### Mader, A. (2003)

Metabolic modelling of endurance performance.

- Status: **Explicit**
- Used for:
  - Mader-style forward power-duration model.
  - MLSS and FatMax inference.
- Main modules:
  - `metabolic_profiler.py`
  - `bayesian_profiler.py`

### Nolte et al. (2025)

Review of Mader-style metabolic constants and model variants.

- Status: **Explicit**
- Used for:
  - Alternative population-specific constants.
  - Documentation of uncertainty around model constants.
- Main modules:
  - `metabolic_profiler.py`
  - `CHANGELOG.md`

### Beneke, R. (2003)

Lactate kinetics and training-status effects around maximal lactate steady
state.

- Status: **Explicit / Contextual**
- Used for:
  - Lactate time-constant priors by athlete context.
- Main modules:
  - `athlete_context.py`
  - `metabolic_profiler.py`

### Coyle, E. F.; Joyner, M. J.; Coyle, E. F. (1991, 2008)

Mechanical efficiency and endurance-performance determinants.

- Status: **Explicit / Contextual**
- Used for:
  - Mechanical efficiency priors.
  - Athlete-context adjustment.
- Main modules:
  - `athlete_context.py`
  - `metabolic_profiler.py`

## 3. W' balance and anaerobic work capacity

### Skiba, P. F. et al. (2008, 2012)

Critical Power and W' balance modelling.

- Status: **Explicit**
- Used for:
  - W' depletion above CP.
  - Exponential W' reconstitution below CP.
  - Default recovery time constant around 546 s.
- Main modules:
  - `power_engine.py`
  - `w_prime_balance_engine.py`

### Bartram et al. (2017)

Revised W' balance modelling and interval-performance interpretation.

- Status: **Explicit / Contextual**
- Used for:
  - W' balance model context and recovery refinements.
- Main modules:
  - `w_prime_balance_engine.py`

## 4. Training load, fitness-fatigue, and detraining

### Banister, E. W. and collaborators (1970s)

Impulse-response fitness-fatigue model.

- Status: **Explicit / Algorithmic**
- Used for:
  - Chronic Training Load.
  - Acute Training Load.
  - Training Stress Balance.
  - Exponential time constants for training-load response.
- Main modules:
  - `detraining_engine.py`

### Foster, C. (1998)

Training monotony and strain.

- Status: **Explicit**
- Used for:
  - Weekly monotony.
  - Strain estimate.
- Main modules:
  - `training_variability_engine.py`

### Gabbett, T. J. (2016); Hulin et al. (2016)

Acute:Chronic Workload Ratio and injury-risk interpretation.

- Status: **Explicit / Contextual**
- Used for:
  - ACWR metric and risk-zone labels.
- Main modules:
  - `training_variability_engine.py`

### Mujika, I.; Padilla, S. (2000, 2001); Coyle et al. (1984)

Detraining effects on VO2max and metabolic capacity.

- Status: **Explicit**
- Used for:
  - Daily decay rates in metabolic state.
  - VO2max and VLamax longitudinal tracking priors.
- Main modules:
  - `detraining_engine.py`
  - `metabolic_kalman.py`

## 5. Bayesian inference and uncertainty

### Haario, H.; Saksman, E.; Tamminen, J. (2001)

**An adaptive Metropolis algorithm**. Bernoulli.

- Status: **Explicit / Algorithmic**
- Used for:
  - Adaptive Metropolis-Hastings sampler.
  - Proposal covariance adaptation.
  - Acceptance-rate diagnostics.
- Main modules:
  - `bayesian_profiler.py`

### Student-t robust likelihood

- Status: **Algorithmic**
- Used for:
  - Robust fitting of MMP residuals.
  - Reduced sensitivity to outlier efforts.
- Main modules:
  - `bayesian_profiler.py`

## 6. Kalman filtering and residual learning

### Julier, S. J.; Uhlmann, J. K. (1997); Wan, E. A.; van der Merwe, R. (2000)

Unscented transform and Unscented Kalman Filter for nonlinear state estimation.

- Status: **Algorithmic**
- Used for:
  - Sigma-point generation.
  - Nonlinear predict/update of `[VO2max, VLamax]`.
- Main modules:
  - `metabolic_kalman.py`

### He, K. et al. (2015)

Residual learning.

- Status: **Explicit / Contextual**
- Used for:
  - Neural residual correction on top of the Mader model.
  - Near-zero initialization philosophy.
- Main modules:
  - `neural_ode.py`

## 7. HRV, DFA-alpha1, and threshold detection

### Peng, C.-K. et al. (1990s)

Detrended fluctuation analysis for heart-rate variability.

- Status: **Explicit / Algorithmic**
- Used for:
  - DFA-alpha1 computation.
  - Log-log fluctuation scaling.
- Main modules:
  - `hrv_engine.py`
  - `analysis.py`

### Gronwald et al.; Rogers and Gronwald (2020)

DFA-alpha1 thresholds around aerobic and anaerobic transition points.

- Status: **Explicit**
- Used for:
  - VT1 threshold near DFA-alpha1 = 0.75.
  - VT2 threshold near DFA-alpha1 = 0.50.
- Main modules:
  - `hrv_engine.py`
  - `cardiac_engine.py`

### Cole, C. R. et al. (1999); Imai et al. (1994)

Heart-rate recovery after exercise.

- Status: **Explicit / Contextual**
- Used for:
  - HRR60 and HRR120 interpretation.
- Main modules:
  - `cardiac_engine.py`

## 8. Cardiac drift and decoupling

### Friel, J.; Maunder and collaborators

Aerobic decoupling and Pa:Hr interpretation.

- Status: **Explicit / Contextual**
- Used for:
  - Power-to-heart-rate decoupling.
  - Endurance-session aerobic efficiency labels.
- Main modules:
  - `cardiac_engine.py`

### Coyle, E. F. (2001); Lambert, M. I. (2008)

Cardiac drift, dehydration, thermoregulation, and fatigue.

- Status: **Explicit / Contextual**
- Used for:
  - Cardiac drift interpretation.
  - Internal-load classification.
- Main modules:
  - `cardiac_engine.py`
  - `thermal_engine.py`

## 9. Thermal physiology and heat acclimation

### Gonzalez-Alonso et al. (1999, 2008)

Core temperature, cardiovascular strain, and exercise fatigue.

- Status: **Explicit**
- Used for:
  - Critical core-temperature zones.
  - Thermal contribution to cardiac drift.
- Main modules:
  - `thermal_engine.py`

### Rowell, L. B. (1974)

Human cardiovascular response to heat stress and exercise.

- Status: **Explicit / Contextual**
- Used for:
  - Approximate HR increase per degree Celsius.
- Main modules:
  - `thermal_engine.py`

### Lorenzo et al. (2010)

Heat acclimation and endurance performance.

- Status: **Explicit**
- Used for:
  - Heat-acclimation trend interpretation.
- Main modules:
  - `thermal_engine.py`

### Periard et al. (2021)

Heat stress, endurance performance, and heat-acclimation physiology.

- Status: **Explicit**
- Used for:
  - Power-loss interpretation above elevated core temperature.
  - Heat adaptation context.
- Main modules:
  - `thermal_engine.py`

## 10. Durability, fatigue resistance, and metabolic flexibility

### Riis; Paton (2022)

Durability and fatigue resistance in cycling performance.

- Status: **Explicit**
- Used for:
  - Durability Index concept.
  - First-hour vs late-hour power comparison.
- Main modules:
  - `durability_engine.py`

### Leo et al. (2022); Clark et al. (2018)

Time-to-exhaustion sustainability and fatigue-resistance indices.

- Status: **Explicit / Contextual**
- Used for:
  - TTE decay interpretation.
  - Fatigue-resistance labels.
- Main modules:
  - `durability_engine.py`

### San-Millan, I.; Brooks, G. A. (2017, 2018)

Mitochondrial function and metabolic flexibility.

- Status: **Explicit**
- Used for:
  - Metabolic flexibility framing.
  - FatMax relative to threshold.
- Main modules:
  - `durability_engine.py`
  - `metabolic_flexibility_engine.py`

### Jeukendrup, A.; Achten, J.; Wallis, G. (2001, 2005)

Fat oxidation, FatMax, and substrate use during exercise.

- Status: **Explicit / Contextual**
- Used for:
  - Fat oxidation estimate around FatMax.
  - Crossover between carbohydrate and fat metabolism.
- Main modules:
  - `metabolic_flexibility_engine.py`

## 11. Lab anchoring and validation status

### Lab data sources

- Status: **Explicit**
- Sources handled by code:
  - spirometry system.
  - metabolic profiling platform.
  - metabolic profiling platform.
  - Lactate analyzers.
  - Manual or JSON input.
- Main modules:
  - `lab_data.py`
  - `metabolic_kalman.py`

### Current validation limitation

- Status: **Explicit**
- The backend can ingest lab data, but the repository does not yet document
  external validation comparing model outputs to a cohort of lab tests.
- Recommended future validation:
  - VO2max estimate vs spirometry.
  - MLSS estimate vs lactate step test.
  - FatMax estimate vs indirect calorimetry.
  - DFA-alpha1 VT1/VT2 vs ventilatory or lactate thresholds.
  - W' balance vs controlled interval tests.
  - Thermal drift vs body-temperature sensor data and controlled heat sessions.

## 12. Recent literature (2024–2025) — implementation notes

### Sempere-Ruiz et al. (2024)

DFA-α₁ thresholds for aerobic (HRVT1) and anaerobic (HRVT2) transitions in
cycling power output.

- Status: **Validated** (thresholds already implemented)
- Used for:
  - Canonical DFA-α₁ cutoffs **0.75** (VT1) and **0.50** (VT2) in `hrv_engine.py`.
  - No code change required; supports existing HRV threshold policy.
- Main modules:
  - `engines/recovery/hrv_engine.py`

### Oliveira et al. (2024)

Meta-analysis on polarized vs pyramidal training distribution.

- Status: **Validated** (interpretation only)
- Used for:
  - Coach-facing Seiler distribution text: POL and PYR are valid patterns;
    POL is not universally superior across all endurance surrogates.
- Main modules:
  - `engines/metabolic/zones_engine.py`

### Jones, A. M. (2024)

The fourth dimension of the power–duration relationship.

- Status: **Validated** (review context for W′ reconstitution)
- Citation: Jones, A. M. (2024). *J Physiol* **602**:4113–4128. doi:[10.1113/JP284205](https://doi.org/10.1113/JP284205)
- Used for:
  - Background for W′ reconstitution τ models (`tau_model` scaffold: `skiba_default`,
    `bartram_elite`, `pugh_level_based`, `individualized`).
  - Distinct from the EJAP 2025 review that cites Jones as a contributor.
- Main modules:
  - `engines/performance/w_prime_balance_engine.py`
  - `engines/core/science_contracts.py`
  - `api/schemas.py` (`tau_model` on snapshot and feasibility requests)

### Wackerhage et al. (2025)

Systematic review on VLamax estimation and interpretation in cycling.

- Status: **Validated** (interpretation / wording)
- Used for:
  - Coach-facing VLamax semantics: **estimated lactate accumulation rate**, not direct
    glycolytic flux; conservative limitations without automatic cadence correction.
- Main modules:
  - `engines/metabolic/metabolic_profiler.py`
  - `engines/core/science_contracts.py`

### Spragg et al. (2023)

Empirical predictors of durability / critical-power decline (DCP).

- Status: **Emerging** (empirical basis for resilience envelope)
- Used for:
  - Top-level `physiological_resilience` contract mapping Mader DCP outputs for coaches.
- Main modules:
  - `engines/performance/physiological_resilience.py`
  - `engines/io/workout_summary.py`

### EJAP cadence / Mader review (2025)

Cadence dependence in Mader-type metabolic modelling.

- Status: **Emerging** (metadata + warnings only; no cadence-dependent VLamax correction)
- Used for:
  - VLamax presented as **estimated lactate accumulation rate**, not direct glycolytic flux.
  - Cadence/protocol warnings on metabolic snapshots.
  - Explicit non-recommendation of automatic cadence-dependent VLamax correction.
- Main modules:
  - `engines/metabolic/metabolic_profiler.py`
  - `engines/core/science_contracts.py`

### Physiological resilience naming

- Status: **Implementation candidate**
- Used for:
  - Top-level `physiological_resilience` contract aggregating existing Mader DCP /
    durability outputs without changing underlying engines.
- Main modules:
  - `engines/performance/physiological_resilience.py`
  - `engines/io/workout_summary.py`

## Suggested citation language

The backend implements a scientific analytics stack based on peer-reviewed
models from power-duration analysis, metabolic modelling, HRV signal processing,
training-load theory, Bayesian inference, Kalman filtering, and thermal
physiology. Several components are direct implementations of published formulas
(for example Coggan power metrics, CP/W', DFA-alpha1, and Banister-style load
models), while other components are evidence-informed engineering models that
require external validation before being used as clinical or laboratory-grade
measurements.
