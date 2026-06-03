# Digital Twin Backend v5.0.0

Stateless Python analytics backend for endurance cycling. Processes FIT
files and produces metabolic profiles, HRV analysis, training load,
session classification, longitudinal tracking (Kalman), and thermal
analysis from 29 engine modules.

Designed for coach-facing applications. No global state, no DB access —
engines are pure functions of their inputs.

## Status

**MVP / pre-production.** 29 engines, 146 public symbols, 459/459 tests.
Algorithms from peer-reviewed literature (Mader, Skiba, Coggan, Banister,
Buchheit & Laursen, Mujika, González-Alonso, Périard). No external
validation against lab testing has been performed yet.

## Install

```bash
pip install -e .
# or: pip install -e ".[dev]" for test dependencies
```

Requires Python ≥3.10, numpy, scipy, fitparse. No PyTorch/JAX/TensorFlow.

## Architecture (v5.0.0)

```
FIT file → fit_parser → interval_detector
                              │
                    ┌─────────┴─────────┐
                  TEST               HIIT/STEADY/FREE
                    │                    │
            qualified_anchors      stimulus_vector
                    │                    │
                    ▼                    ▼
            bayesian_profiler    ──→  metabolic_kalman  ←── lab_data
            (MCMC posterior)          (UKF tracking)        (lab anchor)
                    │                    │
                    └────────┬───────────┘
                             ▼
                      neural_ode (learnable corrections)
```

Additional engines: `pedaling_balance` (L/R), `thermal_engine` (body-temperature sensor),
`race_prediction_engine` (GPX race simulation), `mmp_quality`,
`expressiveness`, `protocol_completeness`.

## What's new

### v5.0.0 — Kalman + Neural ODE + Thermal + Lab Ingestion

- **`metabolic_kalman`**: Unscented Kalman Filter tracks [VO₂max, VLamax]
  daily. Predict (decay + stimulus) and update (test anchors or lab data).
- **`neural_ode`**: Physics-informed MLP learns athlete-specific corrections
  to Mader (NeuralPowerDuration) and training dynamics (NeuralDynamics).
  Pure numpy, 97-114 trainable parameters, zero external ML dependencies.
- **`thermal_engine`**: core body temperature analysis — cardiac drift
  decomposition (thermal vs fatigue), heat tolerance threshold, η correction,
  heat acclimation tracking.
- **`lab_data`**: Universal intake for lab results (spirometry systems,
  metabolic profiling platforms, lactate analyzers, any source). Manual entry, PDF
  parsing, or JSON API. Feeds into Kalman as gold-standard observation.
- **`race_prediction_engine`**: GPX route ingestion for distance, elevation and
  climb profile; simulates race time, energy demand, fueling needs and pacing
  strategy from athlete power/metabolic inputs.

### v4.0.0 — Bayesian Metabolic Profiler

- **`bayesian_profiler`**: Adaptive Metropolis-Hastings MCMC on the Mader
  model. Produces posterior distributions (CI95) instead of point estimates.
  Warm-start from least-squares, Student-t likelihood, duration weights.
  ~0.5s per athlete, pure numpy.

### v3.6.0 — Pedaling Balance

- **`pedaling_balance`**: L/R asymmetry, intra-session drift, balance by
  zone, longitudinal trend. Strict dual-side-only policy with data-driven
  fallback detection. Validated on dual-side power meter real data.

### v3.5.0 — Expressiveness Gate + Mader Constants

- **`ExpressivenessReport`**: masks unreliable parameters when MMP coverage
  is missing for the corresponding physiological window.
- **`MaderConstants`**: overridable with provenance tracking.
- **`protocol_completeness()`**: plans onboarding tests to fill gaps.

### v3.4.0 — Session Classifier

- **`interval_detector`**: TEST/HIIT/STEADY/FREE with 10+7+4+3 subtypes.
  Three-strategy cascade (filename → laps → signal). 9/9 on real FIT files.

### v3.3.x — MMP Quality

- **`mmp_quality`**: artifact detection, cleaning, display gating.


## Tier classification

Every output is labeled by methodological tier. Use this in your UI to
communicate uncertainty honestly to coaches and athletes.

| Tier | Meaning | Modules |
|------|---------|---------|
| **A — REFERENCE** | Deterministic from input. Standard formulas. | `fit_parser`, `power_engine`, `zones_engine`, `coggan_classifier`, `cardiac_engine`, `data_quality_engine`, `efforts_analyzer`, `workout_summary`, `chart_builder`, `pedaling_balance`, `interval_detector` |
| **B — MODEL** | Physiological model with documented assumptions. | `metabolic_profiler` (Mader), `bayesian_profiler` (MCMC), `metabolic_kalman` (UKF), `neural_ode`, `hrv_engine` (DFA-α₁), `w_prime_balance_engine` (Skiba), `thermal_engine`, `lab_data` |
| **C — HEURISTIC** | Rule-of-thumb thresholds, disputed cutoffs. | `metabolic_profiler_phenotype`, `detraining_engine`, `durability_engine`, `training_variability_engine`, `metabolic_flexibility_engine`, `metabolic_current`, `explainability_engine` |
| **D — EXPERIMENTAL** | Single-paper claims or undocumented heuristics. | (none currently — placeholder for future) |

In code:

```python
from engines import Tier, ENGINE_TIERS, annotate

ENGINE_TIERS["power_engine"]        # Tier.REFERENCE
ENGINE_TIERS["durability_engine"]   # Tier.HEURISTIC
ENGINE_TIERS["power_engine"].short  # "A"

result = compute_something(...)
annotate(result, "power_engine")    # adds tier + tier_explanation in-place
```

## What changed in v3.3.0

- **Field naming unified.** `ActivityStreamEnhanced` exposes `power`,
  `heart_rate`, `cadence` directly (was: `power_w`, `heart_rate_bpm`,
  `cadence_rpm` + compat properties). Unit suffixes kept where the unit
  matters (`altitude_m`, `distance_m`, `speed_mps`, `temperature_c`).
  Computed values are properties (`has_power`, `has_heart_rate`, `has_rr`,
  `total_distance_m`, `total_ascent_m`).
- **`sub_sport`, `device_name`** now extracted by the FIT parser and
  propagated through `session_dict`. Previously hardcoded to `None`.
- **`MetabolicProfiler.enhance_with_phenotype()`** added as a fluent
  method. Wraps the standalone function with the profiler's weight already
  supplied. The standalone function still works for users who prefer it.
- **Tier API**: `engines.tiers` module with `Tier` enum, `ENGINE_TIERS`
  mapping, `tier_for()` lookup, and `annotate()` helper. Documents the
  methodological strength of each module's outputs.
- **`SCOPE`** map: which modules are per-activity, which are longitudinal.
- **`hrv_engine`** import cleaned (removed dead fallback
  `from engines.metabolic_profiler import AthleteContext`).
- **`verify_package_integrity.py`** now recognizes type-annotated
  module-level variables (`X: Dict = {}`), not just plain `Assign`.

This is a **breaking change** for anyone reading `stream.power_w` etc.
directly. Migration: rename to `stream.power`.

## What was kept from previous versions

- Real `MetabolicProfiler` class with Mader reverse-engineering (v3.2.1)
- `metabolic_current.get_current_metabolic_status` end-to-end (v3.2.1)
- Phenotype enhancement reads real snapshot fields (v3.2.2)
- `metabolic_current` normalizes `workout_history` dates (v3.2.2)
- `efforts_analyzer` uses `map_aerobic_watts` (v3.2.1)

## Module classification by scope

```
PER-ACTIVITY (one FIT file in, one summary out):
  fit_parser, power_engine, zones_engine, coggan_classifier,
  cardiac_engine, hrv_engine, efforts_analyzer, data_quality_engine,
  workout_summary, chart_builder

LONGITUDINAL (multiple activities or athlete-level context):
  metabolic_profiler, metabolic_profiler_phenotype, metabolic_current,
  detraining_engine, training_variability_engine, durability_engine,
  w_prime_balance_engine, metabolic_flexibility_engine,
  explainability_engine
```

The orchestrator `build_workout_summary` only chains the per-activity
modules. Longitudinal modules are called separately by the service layer
once it has assembled the relevant history.

## Public API entry points

```python
from engines import (
    # Per-activity orchestrator
    build_workout_summary,
    
    # FIT ingestion
    parse_fit_file_enhanced,
    parse_fit_records_enhanced,
    ActivityStreamEnhanced,
    
    # Engines (classes)
    PowerEngine, ZonesEngine, CardiacResponseAnalyzer,
    MetabolicProfiler, MaderConstants, RegularizationWeights,
    
    # Metabolic
    enhance_metabolic_snapshot_with_phenotype,
    get_current_metabolic_status,
    
    # Longitudinal
    calculate_ctl_atl_tsb, apply_detraining_model,
    calculate_acwr, calculate_monotony_strain,
    calculate_w_prime_balance, analyze_w_prime_usage,
    calculate_durability_index, calculate_np_drift,
    calculate_metabolic_flexibility_index,
    
    # Quality + explainability
    assess_data_quality, clean_workout_data,
    calculate_vo2max_confidence, calculate_durability_confidence,
    generate_durability_narrative, generate_acwr_narrative,
    
    # Athlete context
    AthleteContext,
    
    # Tier labels
    Tier, ENGINE_TIERS, tier_for, annotate, SCOPE,
)
```

92 public symbols. Verify with `python3 verify_package_integrity.py engines/`.

## Quickstart

```bash
pip install --break-system-packages numpy scipy fitparse
python3 verify_package_integrity.py engines/         # → 0 issues, 111 symbols
python3 test_e2e.py                                  # → 20/20 PASS
python3 test_metabolic_profiler.py                   # → 33/33 PASS
python3 test_v322_fixes.py                           # → 10/10 PASS
python3 test_v330_refactor.py                        # → 48/48 PASS
python3 test_v332_features.py                        # → 40/40 PASS
python3 test_v340_interval_detector.py               # → 45/45 PASS
python3 test_v350_expressiveness.py                  # → 59/59 PASS
python3 test_v360_pedaling_balance.py                # → 41/41 PASS
python3 test_v400_bayesian.py                        # → 35/35 PASS
python3 test_v500_kalman_neural.py                   # → 34/34 PASS
python3 test_v500_thermal.py                         # → 33/33 PASS
python3 comprehensive_stress_test.py                 # → 61/61 PASS
```

Total: **459/459** tests pass on synthetic + real 1Hz records.
Validation on 9 real FIT files: **9/9 classified correctly**.

## Minimal end-to-end example

```python
from datetime import datetime, timedelta
from engines import (
    parse_fit_records_enhanced,
    build_workout_summary,
    MetabolicProfiler,
    AthleteContext,
)

# 1. Ingest activity (synthetic — replace with parse_fit_file_enhanced for real)
base = datetime(2026, 5, 19, 9, 0)
records = [
    {"timestamp": base + timedelta(seconds=i),
     "power": 220, "heart_rate": 145, "cadence": 88}
    for i in range(3600)
]
stream = parse_fit_records_enhanced(
    records, session_dict={"sport": "cycling", "start_time": base}
)

# 2. Per-activity summary
ctx = AthleteContext(gender="MALE", training_years=5, body_fat_pct=12.0)
summary = build_workout_summary(
    stream=stream, weight_kg=72.0, ftp=280.0, lthr=165, context=ctx,
)
# summary["headline"] → {"tss": 61.5, "normalized_power": 219.5, ...}

# 3. Metabolic snapshot from longitudinal MMP
mmp = {5: 1100, 60: 520, 300: 340, 1200: 295, 3600: 270}
profiler = MetabolicProfiler(weight=72.0, context=ctx)
snapshot = profiler.generate_metabolic_snapshot(mmp)
# snapshot → {"estimated_vo2max": 56.7, "mlss_power_watts": 240.0, ...}

# 4. Add phenotype enhancement (fluent method)
enriched = profiler.enhance_with_phenotype(snapshot, phenotype="ALL_ROUNDER")
# enriched["energy_contributions"], enriched["phenotype_pcr_params"]
```

## Known limitations (honest list)

- Validated on 9 real FIT files (session classification: 9/9). No large-scale validation.
- No validation against lab testing (VO₂max spirometry vs Bayesian estimate).
- No cross-tool agreement study (vs metabolic profiling platform, external analysis platforms).
- Lab PDF parsing is regex-based — works for structured reports, may miss
  unusual layouts. Manual entry is the reliable fallback.
- `fit_parser` now correctly preserves 0W power (coasting) instead of
  treating it as missing data. HR 0 bpm is still treated as sensor dropout.
- Neural ODE requires ≥3 longitudinal snapshots per athlete; with <50 athletes,
  population-level learning is not yet feasible.
- No structured logging — `logging` module is used but not configured.

## Files

```
digital_twin_v5.0.0/
├── pyproject.toml                          # packaging + dependencies
├── VERSION                                 # 5.0.0
├── engines/
│   ├── __init__.py                         # 146 public symbols
│   ├── tiers.py                            # tier classification
│   ├── athlete_context.py                  # athlete metadata + defaults
│   ├── fit_parser.py                       # FIT → ActivityStreamEnhanced
│   ├── power_engine.py                     # NP, IF, VI, TSS, MMP
│   ├── zones_engine.py                     # power/HR zone boundaries
│   ├── coggan_classifier.py                # quadrant analysis
│   ├── cardiac_engine.py                   # cardiac drift, decoupling
│   ├── hrv_engine.py                       # DFA-α₁, RMSSD, pNN50
│   ├── metabolic_profiler.py               # Mader reverse-engineering + expressiveness gate
│   ├── metabolic_profiler_phenotype.py     # diesel/versatile/sprinter
│   ├── mmp_quality.py                      # MMP artifact detection + cleaning
│   ├── interval_detector.py                # TEST/HIIT/STEADY/FREE classifier
│   ├── pedaling_balance.py                 # L/R asymmetry + drift
│   ├── bayesian_profiler.py                # MCMC posterior on Mader
│   ├── metabolic_kalman.py                 # UKF longitudinal tracking
│   ├── neural_ode.py                       # learnable power-duration + dynamics
│   ├── thermal_engine.py                   # core body temperature analysis
│   ├── lab_data.py                         # universal lab test ingestion
│   ├── detraining_engine.py                # CTL/ATL/TSB + detraining decay
│   ├── durability_engine.py                # long-ride power decay
│   ├── w_prime_balance_engine.py           # W' balance (Skiba 2012)
│   ├── training_variability_engine.py      # monotony, strain
│   ├── metabolic_flexibility_engine.py     # fat/CHO transition
│   ├── metabolic_current.py                # integration wrapper
│   ├── data_quality_engine.py              # signal quality flags
│   ├── efforts_analyzer.py                 # peak efforts extraction
│   ├── explainability_engine.py            # human-readable explanations
│   ├── workout_summary.py                  # per-session summary
│   └── chart_builder.py                    # chart data preparation
├── test_e2e.py                             # 20/20
├── test_metabolic_profiler.py              # 33/33
├── test_v322_fixes.py                      # 10/10
├── test_v330_refactor.py                   # 48/48
├── test_v332_features.py                   # 40/40
├── test_v340_interval_detector.py          # 45/45
├── test_v350_expressiveness.py             # 59/59
├── test_v360_pedaling_balance.py           # 41/41
├── test_v400_bayesian.py                   # 35/35
├── test_v500_kalman_neural.py              # 34/34
├── test_v500_thermal.py                    # 33/33
├── comprehensive_stress_test.py            # 61/61
├── validate_on_real_fits.py                # 9/9 real FIT classification
├── verify_package_integrity.py             # AST contract verifier
└── audit.py                                # symbol audit tool
```

Total: 29 engines, 146 symbols, 459 tests, 12 test files.
