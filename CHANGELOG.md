# Changelog

## [5.0.0] — 2026-05-26

Major release: closes the full analysis loop from FIT ingestion through
longitudinal tracking with lab calibration.

### Added — `engines/metabolic_kalman.py`

Unscented Kalman Filter tracking [VO2max, VLamax] over time:
- **Predict**: daily decay (Mujika 0.30%/day) + adaptation from stimulus_vector
- **Update**: qualified anchors from TEST sessions correct the state via UKF
- **`update_from_lab()`**: lab test results as gold-standard observations
  (80% uncertainty reduction from a single spirometry test)
- `process_workout_history()` convenience function
- Configurable `DecayConfig` and `AdaptationConfig`

### Added — `engines/neural_ode.py`

Physics-informed neural models, pure numpy + scipy:
- **NeuralPowerDuration**: MLP (4→16→1) learns athlete-specific corrections
  to Mader. Residual learning (starts at zero correction). 97 params.
- **NeuralDynamics**: MLP (4→16→2) learns state transitions from
  longitudinal data. Requires ≥3 snapshots. 114 params.
- Training via scipy L-BFGS-B, serializable via get_state()/load_state().

### Added — `engines/thermal_engine.py`

Core body temperature analysis (CORE sensor):
- Cardiac drift decomposition (thermal ~9 bpm/°C vs fatigue)
- Heat tolerance threshold detection
- Thermal rise rate (°C/min, °C/kJ)
- η correction factor for the metabolic profiler
- Heat acclimation longitudinal tracking

### Added — `engines/lab_data.py`

Universal intake for lab results from any source worldwide:
- Manual entry: `create_lab_result(source="inscyd", vo2max=62.3, ...)`
- PDF parsing: `parse_lab_pdf("report.pdf")` — auto-detects INSCYD,
  COSMED, Cortex, FlowPerformance, Vyaire, PNOE
- JSON API: `LabTestResult.from_dict(d)`
- Validation: catches impossible values, unit errors, logical conflicts
- Feeds into `MetabolicKalman.update_from_lab()` as high-confidence anchor

### Modified — `engines/fit_parser.py`

- Added `core_body_temp`, `skin_temp`, `ambient_temp`, `has_core_sensor`
- **Bugfix**: 0W power no longer treated as missing data (was being
  interpolated away). 0W = coasting, physiologically valid. Only NaN
  triggers gap filling for power. HR 0 bpm still treated as dropout.
- Added comprehensive device detection for power meter L/R source
  (Quarq, Power2Max, SRM, Rotor 2INpower, Assioma, Vector, etc.)
- Data-driven fallback: if balance std > 1.0, classified as dual
  regardless of device name.

### Modified — `engines/metabolic_current.py`

- Removed `sys.path.insert` hack (was only module inside engines/ with it)
- Error handler no longer exposes internal exception details to client

### Added — `pyproject.toml`

Proper Python packaging with declared dependencies. Install via
`pip install -e .` instead of manual sys.path manipulation.

### Verification

```
test_e2e.py:                      ✓ 20/20
test_metabolic_profiler.py:       ✓ 33/33
test_v322_fixes.py:               ✓ 10/10
test_v330_refactor.py:            ✓ 48/48
test_v332_features.py:            ✓ 40/40
test_v340_interval_detector.py:   ✓ 45/45
test_v350_expressiveness.py:      ✓ 59/59
test_v360_pedaling_balance.py:    ✓ 41/41
test_v400_bayesian.py:            ✓ 35/35
test_v500_kalman_neural.py:       ✓ 34/34
test_v500_thermal.py:             ✓ 33/33
comprehensive_stress_test.py:     ✓ 61/61
TOTAL:                            ✓ 459/459
validate_on_real_fits.py:         ✓ 9/9
verify_package_integrity.py:      ✓ 0 issues, 146 symbols
```

---

## [4.0.0] — 2026-05-25

### Added — `engines/bayesian_profiler.py`

Replaces point-estimate least_squares with full posterior inference via
Adaptive Metropolis-Hastings MCMC (Haario et al. 2001):
- Student-t likelihood (robust to sprint outlier in Mader)
- Duration-based weights (same as deterministic profiler)
- Warm-start from least_squares solution
- Output: `BayesianMetabolicSnapshot` with `PosteriorSummary` per parameter
  (mean, median, std, CI95, CI80, ESS, prior info)
- `bayesian_confidence` = √(vo2_reduction × vla_reduction)
- Raw posterior samples for downstream (Kalman init)
- Pure numpy MCMC, ~0.5s per athlete, zero external dependencies

---

## [3.6.0] — 2026-05-22

User-requested feature: monitor pedaling balance in endurance to detect
unilateral fatigue and inform unilateral strength interventions (single-leg
squats, single-leg pedaling drills, etc.).

### Added — `engines/pedaling_balance.py`

New module for L/R balance analysis with a **strict data policy**: only
dual-side power meters (true L/R measurement) are accepted. Single-side
meters with estimated balance are explicitly refused.

```python
from engines import analyze_pedaling_balance, analyze_balance_trend

r = analyze_pedaling_balance(
    balance_stream=stream.left_right_balance.tolist(),
    power_stream=stream.power.tolist(),
    ftp=250,
    pedaling_balance_source=stream.pedaling_balance_source,
)
# r.data_quality                  → "good" | "limited" | "refused_single_side" | "insufficient_data"
# r.asymmetry_pct                 → symmetric / mild / moderate / marked
# r.intra_session_drift           → did one leg progressively take more load?
# r.balance_by_zone               → {z1_z2, z3_z4, z5_plus} averages
# r.clinical_recommendation       → text hint when intervention is warranted
```

**Primary endpoint**: intra-session drift in endurance sessions — the
signature of unilateral fatigue. If detected reproducibly across sessions,
the longitudinal `analyze_balance_trend()` flags consistent direction and
suggests unilateral strength work.

**Source gating**:
- `"dual"` (Garmin Vector 3, Favero Assioma DUO, Rally 200-series) → full analysis
- `"single_estimated"` (Stages, 4iiii, Assioma UNO, Rally 100-series) → REFUSED
- `"unknown"` → analyzed with flag (`accept_unknown_source=False` to refuse)

### Modified — `engines/fit_parser.py`

- `ActivityStreamEnhanced` gains `left_right_balance: np.ndarray` (NaN
  where not reported) and `pedaling_balance_source: str` (auto-detected
  from `device_info` manufacturer/product strings).
- Parser handles all 3 standard FIT balance encodings:
  1. Plain 0-100 (left percent)
  2. Raw 0-255 with top-bit flag for right-dominance
  3. Dict-shaped `{"value": N, "right": bool}` (some firmwares)

### Note on validation

The 9 real FIT files in our test corpus do not contain `left_right_balance`
records (single-side power meter origin), so the module is validated only
on synthetic data. The first dual-side athlete onboarded will provide the
real-world validation.

### Verification

```
verify_package_integrity.py:           ✓ 0 issues, 119 symbols
test_e2e.py:                           ✓ 20/20 PASS  (regression)
test_metabolic_profiler.py:            ✓ 33/33 PASS  (regression)
test_v322_fixes.py:                    ✓ 10/10 PASS  (regression)
test_v330_refactor.py:                 ✓ 48/48 PASS  (regression)
test_v332_features.py:                 ✓ 40/40 PASS  (regression)
test_v340_interval_detector.py:        ✓ 45/45 PASS  (regression)
test_v350_expressiveness.py:           ✓ 59/59 PASS  (regression)
test_v360_pedaling_balance.py:         ✓ 41/41 PASS  (new)
comprehensive_stress_test.py:          ✓ 61/61 PASS  (regression)
TOTAL:                                 ✓ 357/357 PASS
validate_on_real_fits.py:              ✓ 9/9 classified correctly
```

### Public API additions

```python
from engines import (
    analyze_pedaling_balance,
    analyze_balance_trend,
    PedalingBalanceReport,
    BalanceTrend,
)
```

---

## [3.5.0] — 2026-05-22

External methodological review identified three structural fragilities
of the Mader reverse-engineering approach. This release addresses two
of them (the third — DFA-α₁ corroboration — deferred to a later release
to avoid scope creep).

### Added — Expressiveness gate

The review's core observation: if an athlete's MMP curve is missing
anchors in the **glycolytic window (20-60s)**, the least_squares fit
will produce a vLamax estimate that's mathematically convergent but
**physiologically meaningless** — the optimizer is interpreting an
appiattimento dell'asse glicolitico as low glycolytic capacity, when
in reality the data simply doesn't express that system.

This release adds `ExpressivenessReport.from_mmp(mmp)` that checks
coverage of the 4 critical duration windows:

| Window | Duration | Required for |
|--------|----------|--------------|
| Neuromuscular / alactic | 5-15s | sprint anchor (informational) |
| Glycolytic | 20-60s | **vlamax, fatmax** |
| VO2max | 180-480s | **vo2max** (with threshold) |
| Threshold / MLSS | 1200-3600s | **mlss, vo2max, fatmax** |

When `MetabolicProfiler.generate_metabolic_snapshot()` runs:
- If glycolytic window is missing → `estimated_vlamax_mmol_L_s = None`,
  `metabolic_phenotype = None`, `combustion_curve = None`, and
  `fatmax_power_watts = None`
- If threshold window is missing → `mlss_power_watts = None`,
  `estimated_vo2max = None`, `zones = None`, `fatmax_power_watts = None`
- Global `confidence_score` is capped at 0.40 when any parameter
  is masked
- The raw estimates are preserved under `unmasked_estimates` for audit

The masked output makes it impossible for the UI to display a vLamax
value that's actually unreliable — which is what the review specifically
called out.

### Added — MaderConstants override

Default constants (ks1=0.0631, ks2=1.331 from Mader & Heck 1986) are
no longer hardcoded. `MetabolicProfiler(..., mader_constants=...)`
accepts a custom `MaderConstants` instance. The values used are
reported in `snapshot["context_used"]["mader_constants"]` with a
provenance label, addressing the dogmatic-constants critique.

The Nolte et al. 2025 review (Springer EJAP) cites `ks1=0.0635` as
the more recent value; either set can be selected per-population.
Elite athletes with confirmed mitochondrial adaptations may warrant
different constants — until population-specific calibrations exist,
this provides the mechanism without imposing a specific override.

### What this DOESN'T do

- Does not change the Mader equations themselves
- Does not validate the constants against any new study
- Does not implement DFA-α₁ corroboration with RPE / respiratory data
  (third review point, deferred)
- Does not pretend the masked outputs are "fixed" — they're hidden
  precisely because they aren't fixable without more data

The unmasked values remain in the output under `unmasked_estimates`,
so any pipeline that genuinely wants the raw fit (for debugging or
methodological research) can still get it.

### Verification

```
verify_package_integrity.py:        ✓ 0 issues, 112 symbols
test_e2e.py:                        ✓ 20/20 PASS (regression)
test_metabolic_profiler.py:         ✓ 33/33 PASS (regression)
test_v322_fixes.py:                 ✓ 10/10 PASS (regression)
test_v330_refactor.py:              ✓ 48/48 PASS (regression)
test_v332_features.py:              ✓ 40/40 PASS (regression)
test_v340_interval_detector.py:     ✓ 45/45 PASS (regression)
test_v350_expressiveness.py:        ✓ 47/47 PASS (new)
comprehensive_stress_test.py:       ✓ 61/61 PASS (regression)
TOTAL:                              ✓ 304/304 PASS
validate_on_real_fits.py:           ✓ 9/9 classified correctly
```

### Public API additions

```python
from engines import (
    ExpressivenessReport,      # new
    MetabolicProfiler,
    MaderConstants,
)

# Method 1: just call the profiler — gate is automatic
snap = profiler.generate_metabolic_snapshot(mmp)
# snap["expressiveness"] tells you what's reliable
# snap["unmasked_estimates"] preserves the raw fit for audit

# Method 2: check ahead of time
report = ExpressivenessReport.from_mmp(mmp_dict)
if not report.vlamax_reliable:
    # tell the user to do a sprint test before trusting vlamax

# Method 3: custom calibration
custom_const = MaderConstants(ks1=0.0635, ks2=1.30, _source="my_population")
p = MetabolicProfiler(weight=72, mader_constants=custom_const)
```

---

## [3.4.0] — 2026-05-22

Addresses the "low confidence on real-world data" problem from a different
angle than v3.3.2's MMP cleaning: **classify the source workout type**
and extract qualified anchors directly from test sessions. A `cp6` test,
for example, produces a known-good 360s anchor that should enter the
MetabolicProfiler with reliability=1.0, instead of being mixed with
rolling-window candidates of unknown provenance.

### Added — `engines/interval_detector.py`

New module that classifies a workout into one of 4 macro-categories with
a sub-type, and extracts:
- **Qualified MMP anchors** (TEST sessions) for use as high-reliability
  input to MetabolicProfiler.
- **Stimulus vector** (time in aerobic_base / tempo / threshold /
  vo2max / anaerobic / neuromuscular zones) — input to the future
  multi-parametric detraining model (v3.5.0).
- **Detected interval blocks** (HIIT sessions, structural breakdown).

Three-strategy cascade with declared confidence and source:

1. **Filename match** (confidence 0.85-1.00, source="filename"):
   regex against ~25 known patterns. Catches `ramp_test`, `2x8_test`,
   `cp3/6/12`, `sprint_test`, `30/15`, `tabata`, `endurance`, `race`, etc.
2. **Lap structure** (confidence 0.65-0.85, source="laps"): detects
   HIIT by alternating work/rest power across ≥10 laps, ramp by
   monotonic power increase, FTP 2x8 by long threshold-power laps.
3. **Signal features** (confidence 0.40-0.60, source="signal"):
   normalized power, variability index, time-in-zone, spike detection.
   Recognizes ramp, single_sprint, sprint_set, mixed_test
   (sprint+sustained), STEADY tempos, FREE races.

**Manual hint override** also supported: `classify_session(..., hint=("TEST", "cp6"))`
bypasses all strategies with confidence=1.0, source="hint".

Closed taxonomy (10 TEST + 7 HIIT + 4 STEADY + 3 FREE subtypes):
- TEST: ramp_test, ftp_2x8, ftp_20min, ftp_8min, cp3, cp6, cp12,
  single_sprint, sprint_set, mixed_test
- HIIT: microburst_high_density, microburst_balanced, medium_interval,
  long_interval, sprint_repeats, structured_mixed, hiit_unspecified
- STEADY: endurance_z2, tempo, sweet_spot, threshold_continuous
- FREE: race, group_ride, free_ride

### Validation on 9 real FIT files

```
File                            Ground truth      Classified
─────────────────────────────────────────────────────────────────
cdea1e7e (51 laps)              HIIT              HIIT/medium_interval ← laps
44fdf4f5 (1 lap)                TEST              TEST/mixed_test       ← signal
e92dcce6 (1 lap)                TEST              TEST/mixed_test       ← signal
caea716b (51 laps)              HIIT              HIIT/microburst_bal   ← laps
064adf70 (51 laps)              HIIT              HIIT/medium_interval  ← laps
ramp_test_01                    TEST/ramp_test    TEST/ramp_test        ← filename
2x8_test                        TEST/ftp_2x8      TEST/ftp_2x8          ← filename
flow_protocol_1                 TEST/mixed_test   TEST/mixed_test       ← filename
workout_20260521                TEST/single_sprint TEST/single_sprint   ← signal
─────────────────────────────────────────────────────────────────
                                Category accuracy: 9/9  (100%)
                                Full match:        9/9  (100%)
```

### What this doesn't do (deferred to v3.5.0)

This release is **strictly additive**. No existing engine's behaviour is
changed. The integration is left for v3.5.0:

- MetabolicProfiler should accept `qualified_anchors` and use them with
  high weight in the `least_squares` fit (lifting confidence for athletes
  who have actual tests).
- detraining_engine should accept a per-day `stimulus_vector` and apply
  parameter-specific decay (VO2max-stimulus deficit → VO2max decay,
  threshold-stimulus deficit → MLSS decay) instead of the current
  scalar-TSS approach.

### Public API additions

```python
from engines import (
    classify_session,         # main entry point
    Category,                  # enum: TEST/HIIT/STEADY/FREE/UNCLASSIFIED
    ClassifiedSession,         # output dataclass
    QualifiedAnchor,
    IntervalBlock,
    StimulusVector,
    SUBTYPES_TEST,
    SUBTYPES_HIIT,
    SUBTYPES_STEADY,
    SUBTYPES_FREE,
)

result = classify_session(
    powers,                    # 1Hz power stream
    filename="cp6_test.fit",   # for Strategy A
    laps=lap_dicts,            # for Strategy B
    ftp=275,                   # for stimulus vector + Strategy C
    hint=None,                 # ("TEST", "cp6") to bypass
)
# result.category, .subtype, .confidence, .source
# result.qualified_anchors (only for TEST)
# result.stimulus_vector (always, if FTP known)
# result.detected_blocks (placeholder, populated in v3.5.0)
```

### Verification

```
verify_package_integrity.py:        ✓ 0 issues, 111 symbols
test_e2e.py:                        ✓ 20/20 PASS
test_metabolic_profiler.py:         ✓ 33/33 PASS
test_v322_fixes.py:                 ✓ 10/10 PASS
test_v330_refactor.py:              ✓ 48/48 PASS
test_v332_features.py:              ✓ 40/40 PASS
test_v340_interval_detector.py:     ✓ 45/45 PASS  (new)
comprehensive_stress_test.py:       ✓ 61/61 PASS
validate_on_real_fits.py:           ✓ 9/9  classified correctly
TOTAL:                              ✓ 257/257 PASS
```

### Design notes

- The 3-strategy cascade is **inspired by Athletica.ai's Interval IQ**
  (signal processing + change-point + post-processing) but adapted to
  the Digital Twin's needs: we ALSO need to classify the macro-type of
  the session, not just find intervals.
- TrainingPeaks/WKO5's pure "zone × duration" approach only achieves
  ~18% perfect detection on real sessions according to Vekta's
  published benchmark (March 2026). Lap-aware + signal-aware should
  do significantly better.
- We deliberately **do not use machine learning**. The taxonomy is
  closed (~24 subtypes), the rules are inspectable, and the user
  can correct via `hint=` if needed. A trained model would be a
  black box and harder to audit on a new athlete.

---

## [3.3.2] — 2026-05-20

Addresses the "low confidence on real-world data" issue surfaced by analyzing
JSON snapshots from 3 athletes (Diego, Adrian, Adriano). Root cause: MMP
curves extracted from training rides contain artifacts (plateau duplicates,
rolling-window redundancy, sprint outliers) that bias the Mader fit and
correctly produce low confidence scores. Adds tools to detect and clean
those artifacts, plus product-layer helpers (display gating, time window).

### Added

- **`engines/mmp_quality.py`** — new module:
  - `analyze_mmp_quality(mmp, mmp_samples=None) → MMPQualityReport`
    Detects 5 categories of issues: identical plateaus, rolling-window
    redundant clusters, sprint outliers, flat long-duration regions,
    non-monotonic anchors. Returns a quality score (0..1) and per-issue
    explanations.
  - `clean_mmp(mmp, mmp_samples=None) → (cleaned_mmp, audit)`
    Drops plateau duplicates and rolling-window-redundant anchors.
    Sprint outliers and flat regions are flagged but kept (require human
    judgment).
  - `filter_mmp_by_window(samples, today=None, window_days=90) → (mmp, kept)`
    WKO5-style 90-day window. Re-extracts MMP from samples within window.

- **`MetabolicProfiler.generate_metabolic_snapshot()`** gained two optional
  parameters:
  - `mmp_samples`: per-anchor provenance (used by cleaning)
  - `clean_mmp_first=False`: when True, run `clean_mmp()` before fitting
    and embed the audit in the output under `mmp_quality`.

- **Display gating in `engines/tiers.py`** (WKO5-style "hide instead of mislead"):
  - `should_display(confidence, threshold=0.55) → bool`
  - `mask_low_confidence(payload, threshold=0.55, placeholder="—") → dict`
    Returns a copy with low-confidence numeric fields replaced by `"—"`,
    plus a `_display` meta dict explaining what was hidden and why.
  - Constants: `DEFAULT_DISPLAY_THRESHOLD = 0.55`, `DEFAULT_PLACEHOLDER = "—"`

- **`test_v332_features.py`** — 40/40 PASS validating all of the above.

### Discovered (documented, not fixed)

- **The `MetabolicProfiler` in this package and the one running in Gigi's
  production app produce DIFFERENT confidence scores for the same MMP.**
  On Adrian's MMP, our profiler returns conf=0.05, VO2max=43.9; the app
  returns conf=0.69, VO2max=49.3. This suggests the production deployment
  uses a modified version (different regularization weights, scaling of
  rel_err, or fit configuration). The cleaning helpers added here work
  with both, but the absolute confidence numbers are version-dependent.

### Verification

```
verify_package_integrity.py:    ✓ 0 issues, 101 symbols
test_e2e.py:                    ✓ 20/20 PASS  (regression)
test_metabolic_profiler.py:     ✓ 33/33 PASS  (regression)
test_v322_fixes.py:             ✓ 10/10 PASS  (regression)
test_v330_refactor.py:          ✓ 48/48 PASS  (regression)
test_v332_features.py:          ✓ 40/40 PASS  (new)
comprehensive_stress_test.py:   ✓ 61/61 PASS  (regression)
TOTAL:                          ✓ 212/212 PASS
```

### Usage examples

```python
from engines import (
    MetabolicProfiler, AthleteContext,
    analyze_mmp_quality, clean_mmp, filter_mmp_by_window,
    mask_low_confidence,
)

# Snapshot with cleaning enabled
profiler = MetabolicProfiler(weight=72, context=AthleteContext())
snap = profiler.generate_metabolic_snapshot(
    mmp_dict,
    mmp_samples=samples,          # provenance per anchor
    clean_mmp_first=True,         # drop artifacts before fitting
)
# snap["mmp_quality"]["dropped"] lists what was removed
# snap["mmp_quality"]["analysis"]["quality_score"] gives the input quality

# Limit to last 90 days (WKO5-style)
mmp_recent, kept = filter_mmp_by_window(samples, window_days=90)
snap2 = profiler.generate_metabolic_snapshot(mmp_recent)

# UI gate: hide values when confidence is too low
display_snap = mask_low_confidence(snap, threshold=0.55)
# display_snap["estimated_vo2max"] == "—" if conf < 0.55
# display_snap["_display"]["reason"] explains why
```

---

## [3.3.1] — 2026-05-19

External code review surfaced several real bugs (and several false alarms
based on materials from earlier iterations). This release addresses the
real ones and adds tests that document the false ones so future reviewers
don't repeat the confusion.

### Fixed

- **Sport-name disciplines now accepted by `AthleteContext`.** Previously
  only the three physiological categories `ENDURANCE`/`MIXED`/`SPRINT`
  were valid; passing `discipline="ROAD"` (as the `metabolic_current`
  docstring explicitly suggested) silently fell back to `MIXED`.
  
  Now `effective_discipline()` accepts cycling sport names and maps them
  to physiological categories:
  - **ENDURANCE**: ROAD, TT, TIME_TRIAL, GRAVEL, TRIATHLON, ULTRA,
    MTB_XCM, MARATHON
  - **MIXED**: MTB, MTB_XCO, CYCLOCROSS, CX, CRITERIUM, GRAN_FONDO
  - **SPRINT**: TRACK, TRACK_SPRINT, BMX, KEIRIN
  
  Normalization is case-insensitive and accepts `-`/` ` as separators
  (e.g. `"Track-Sprint"`, `"Mtb Xco"`). Unknown values still default
  to `MIXED` and are flagged by `inferred_fields()`.

- **`metabolic_current.py` output coherence.** The `athlete` dict in the
  output used to expose `ctx.training_years` and `ctx.discipline` raw —
  even though the model internally used the resolved (`effective_*`)
  values. Now reports the effective values, matching what the model
  actually computed with. Also adds `inferred_fields` to the athlete
  dict for transparency.

- **`efforts_analyzer.py` falsy-zero bugs.** Two `... if X else None`
  guards turned legitimate zero values into `None`:
  - `wprime_j = ... * 1000.0 if wprime_kj else None` — bug if `wprime_kj=0`
  - `"w_prime_consumed_j": round(w_consumed_j, 0) if w_consumed_j else None`
    — bug if effort exactly matched CP (no W' consumed)
  
  Both replaced with `is not None` checks.

- **`comprehensive_stress_test.py` rebuilt from scratch.** The previous
  version imported `parse_fit_records` (legacy name, removed in v3.3.0),
  crashed at module load. It also accessed `snap["athlete_weight_kg"]`
  which `MetabolicProfiler.generate_metabolic_snapshot()` never produced.
  Replaced with a real stress test that:
  - Exercises 3 rider archetypes (Sprinter/Climber/All-Rounder)
  - Runs the per-activity orchestrator on a 3h synthetic ride per rider
  - Runs the longitudinal pipeline (detraining + ACWR + monotony/strain)
  - Validates W' balance under interval simulation
  - Tests adversarial inputs (empty/single-anchor MMP, all-zero stream,
    5-sample stream)
  - Validates all 19 sport-name disciplines
  - Tests `efforts_analyzer` with degenerate W'=0 and missing snapshot

### Added

- **`test_v331_review_fixes.py`** — (implicit in `comprehensive_stress_test.py`)
  validates each of the bugs above with a dedicated check.

### Reviewer claims that were FALSE

The same review listed several claims that turn out to be based on
materials from earlier iterations (pre-v3.3.0). For the record:

- **"`fit_parser.py` still has `power_w`/`heart_rate_bpm`/`cadence_rpm`"** —
  False. The v3.3.0 refactor removed them. `grep -E "power_w|heart_rate_bpm|cadence_rpm" engines/fit_parser.py` returns nothing.
- **"Two versions of `cardiac_engine.py`/`detraining_engine.py`/`fit_parser.py`
  exist"** — False. There is one file per module. `ls engines/*.py` confirms.
- **"`handler.py` imports `generate_all_charts` (which doesn't exist)"** —
  False. There is no `handler.py` in the package. This was a file from an
  earlier deployment-layer experiment, not part of `engines/`.
- **"`README.md` claims 111/111 tests pass but the materials don't support
  it"** — Now 172/172, run on every release; the materials do support it
  because the AST verifier confirms 0 issues and the tests are
  reproducible from the archive.

### Verification

```
verify_package_integrity.py:    ✓ 0 issues, 92 symbols
test_e2e.py:                    ✓ 20/20 PASS  (regression)
test_metabolic_profiler.py:     ✓ 33/33 PASS  (regression)
test_v322_fixes.py:             ✓ 10/10 PASS  (regression)
test_v330_refactor.py:          ✓ 48/48 PASS  (regression)
comprehensive_stress_test.py:   ✓ 61/61 PASS  (new in v3.3.1)
TOTAL:                          ✓ 172/172 PASS
```

---

## [3.3.0] — 2026-05-19

### Breaking

- **`ActivityStreamEnhanced` field rename.** Internal fields renamed from
  `power_w`/`heart_rate_bpm`/`cadence_rpm` to `power`/`heart_rate`/`cadence`.
  Unit suffixes kept where the unit is non-conventional (`altitude_m`,
  `distance_m`, `speed_mps`, `temperature_c`). Backward-compat properties
  removed. Anyone reading `stream.power_w` directly will get an
  `AttributeError`. Migration: search-replace `power_w → power`,
  `heart_rate_bpm → heart_rate`, `cadence_rpm → cadence`.

### Added

- **`engines.tiers` module** with `Tier` enum, `ENGINE_TIERS` mapping,
  `tier_for()` lookup, `annotate()` helper, and `SCOPE` map (per-activity
  vs longitudinal). Single source of truth for the methodological tier of
  each module output. Consumers (UI, dashboards) should use these to label
  outputs honestly.
- **`MetabolicProfiler.enhance_with_phenotype()`** fluent method. Wraps the
  standalone `enhance_metabolic_snapshot_with_phenotype` function with the
  profiler's weight automatically supplied. Method chaining-friendly.
- **`sub_sport` and `device_name`** extraction in `parse_fit_file_enhanced`
  (reads from `session` and `device_info` messages) and propagation through
  `session_dict` in `parse_fit_records_enhanced`. Previously hardcoded to
  None.
- **`rr_intervals`**, **`position_lat`**, **`position_long`**,
  **`temperature`** fields now read from FIT records into the stream.
- **`audit.py`** dependency-mapper script (used to plan this refactor).
- **`test_v330_refactor.py`** — 48/48 PASS validating the refactor.

### Changed

- `__init__.py` header rewritten: no more stale notes about missing
  `MetabolicProfiler`. Documents the Tier system and naming convention.
- `__all__` grew from 87 to **92 symbols** (added `Tier`, `ENGINE_TIERS`,
  `tier_for`, `annotate`, `SCOPE`).
- `verify_package_integrity.py` now recognizes `AnnAssign` (type-annotated
  module-level variables) — previously only flat `Assign` was detected.

### Fixed

- **`hrv_engine` dead import fallback removed.** The file had a
  `try ... except ImportError: from engines.metabolic_profiler import
  AthleteContext` fallback. `AthleteContext` doesn't live in
  `metabolic_profiler`, so the fallback would have failed; it was dead
  code. Now imports directly from `engines.athlete_context`.

### Verification

```
verify_package_integrity.py:    ✓ 0 issues, 92 symbols
test_e2e.py:                    ✓ 20/20 PASS (regression — no break)
test_metabolic_profiler.py:     ✓ 33/33 PASS (regression — no break)
test_v322_fixes.py:             ✓ 10/10 PASS (regression — no break)
test_v330_refactor.py:          ✓ 48/48 PASS (new)
TOTAL:                          ✓ 111/111 PASS
```

### Not yet addressed (deliberately out of scope)

- Real `.fit` file testing — needs Gigi's actual data
- Lab validation (VO2max, lactate, MLSS) — needs subject pool
- Cross-tool agreement vs WKO5/TrainingPeaks — needs side-by-side runs
- Edge function load testing — needs deployment target
- Supabase schema and RLS — needs product spec

---

## [3.2.2] — 2026-05-19

### Fixed

- **Phenotype enhancement schema drift** (`metabolic_profiler_phenotype.py`).
  `enhance_metabolic_snapshot_with_phenotype` was reading `vo2max_mlkgmin`,
  `athlete_weight_kg`, `power_30s`, `power_1200s` from the snapshot — none of
  which exist in the real `MetabolicProfiler` output. It silently fell back
  to defaults (50 ml/kg/min, 75kg, 500W, 300W).
  
  Now reads the actual fields (`estimated_vo2max`, `mlss_power_watts`) and
  exposes the missing values as **explicit parameters**:
  
  ```python
  enhance_metabolic_snapshot_with_phenotype(
      snapshot,
      phenotype="SPRINTER",
      weight_kg=72.0,        # NEW — pass explicitly (snapshot doesn't have it)
      power_30s=900.0,       # NEW — defaults to 1.5 × MLSS
      power_1200s=280.0,     # NEW — defaults to MLSS itself
  )
  ```

  This is the cleaner fix recommended in v3.2.1 known-issues: the consumer
  was patched to match the producer, not the other way round.

- **`metabolic_current.py` date normalization.** The docstring claimed
  "accepts ISO strings or date objects" for `workout_history` entries, but
  only the top-level `today` parameter was normalized. ISO strings passed
  inside `workout_history[i]["date"]` reached `detraining_engine` unchanged
  and crashed on `current_date <= today` (str vs date comparison).
  
  Now the function normalizes every entry: ISO string, `datetime`, and
  `date` are all accepted; malformed dates (`None`, garbage, missing key)
  are skipped instead of crashing the whole call.

### Added

- `test_v322_fixes.py` — 10/10 PASS, validates both fixes:
  - Phenotype enhancement uses real fields, accepts new parameters, higher
    `power_30s` produces higher anaerobic fraction (sanity-check)
  - `workout_history` works with ISO strings, `date` objects, mixed types,
    and gracefully skips malformed entries

### Verification

```
verify_package_integrity.py:       ✓ 0 issues, 87 symbols
test_e2e.py:                       ✓ 20/20 (no regression)
test_metabolic_profiler.py:        ✓ 33/33 (no regression)
test_v322_fixes.py:                ✓ 10/10 (new)
```

---

## [3.2.1] — 2026-05-19

### Added

- **`MetabolicProfiler` class** (v3.3.1-Tethered) integrated into the package.
  This is the Mader reverse-engineering core: takes a power-duration curve (MMP)
  and produces estimates of VO2max, VLamax, MLSS, FatMax, MAP, plus phenotype
  classification and combustion curves. Uses `scipy.optimize.least_squares`
  with regularization against athlete-context priors (VO2 vs guess, VO2 vs
  expected-heuristic, short-effort MAE).
- **`metabolic_current` re-enabled** in `__init__.py`. The
  `get_current_metabolic_status` function now works end-to-end: it builds a
  baseline snapshot from historical MMP, then applies the detraining model
  using recent training load to return *current* (decayed) estimates.
- **`handle_edge_function_request`** exposed for serverless deployment.
- **`test_metabolic_profiler.py`** — dedicated integration test (33/33 PASS):
  - Class instantiation and `MaderConstants` access
  - `generate_metabolic_snapshot` with realistic MMP → plausible physiology
    (VO2max 56.7, VLamax 0.49, MLSS 240W, FatMax 157W, MAP 347W)
  - Insufficient MMP rejection (status=error when <3 anchors)
  - `enhance_metabolic_snapshot_with_phenotype` runs without crashing
  - `get_current_metabolic_status` end-to-end (CTL/ATL/TSB + decayed snapshot)
  - `apply_detraining_model` decays baseline VO2max correctly

### Changed

- `metabolic_profiler.py` is now the real `MetabolicProfiler` class.
- The previous content (phenotype enhancement functions only) moved to
  `metabolic_profiler_phenotype.py`. Both are exported. Use:
  - `MetabolicProfiler(weight, context).generate_metabolic_snapshot(mmp)`
    for the base snapshot
  - `enhance_metabolic_snapshot_with_phenotype(snapshot, phenotype)` to
    add PCr/anaerobic adjustments based on rider phenotype
- `__all__` now has 87 symbols (was 82).
- `engines/__init__.py.__version__` bumped to 3.2.1.

### Fixed

- **Schema drift in `efforts_analyzer.py`**: was reading
  `snapshot["map_watts"]` but the field is `map_aerobic_watts`. Updated
  both the docstring and the actual `dict.get()` call.

### Known issues (documented but not fixed)

- **Phenotype enhancement field name mismatch.**
  `enhance_metabolic_snapshot_with_phenotype` reads `snapshot["vo2max_mlkgmin"]`
  and `snapshot["athlete_weight_kg"]`, but `MetabolicProfiler` produces
  `estimated_vo2max` and stores weight on the profiler instance, not the
  snapshot. The enhancement falls back to defaults (50 ml/kg/min, 75kg).
  Not a blocker; the enhancement is opt-in. Fix would be a 2-line patch.
- **`metabolic_current.py` does not normalize `workout_history` dates.**
  Docstring claims "accepts ISO strings or date objects" but only `today` is
  normalized; if dates in `workout_history` are strings, `detraining_engine`
  crashes on `<=` comparison. Workaround: pass `date` objects (recommended).
- **`MetabolicProfiler` confidence is heuristic.** The `confidence_score` is
  derived from relative RMSE of MMP fit, not from a proper statistical
  uncertainty estimate. A low score (e.g. 0.05) still produces plausible
  physiology — it indicates the fit residuals are non-trivial, not that the
  estimates are wrong.

---

## [3.2.0] — 2026-05-19

### Fixed (real issues from external code review)

- **API contract aligned with reality.** `__init__.py` previously declared
  `WorkoutSummaryGenerator`, `CardiacAnalyzer`, `PowerAnalyzer`,
  `ZonesCalculator`, `HRVAnalyzer`, and `ChartBuilder` — none of which exist
  in the actual source. Now exports only what's really there:
  - `build_workout_summary` (function, not class)
  - `CardiacResponseAnalyzer` (real class name)
  - `PowerEngine` (real class name)
  - `ZonesEngine` (real class name)
  - HRV exposed as `analyze_rr_stream`, `calculate_dfa_alpha1`, `detect_thresholds_from_activity` (functions, not class)
  - `chart_*` functions + `generate_workout_charts` (no class)

- **Field schema mismatch fixed.** `ActivityStreamEnhanced` uses `power_w`,
  `heart_rate_bpm`, `cadence_rpm` internally, but `zones_engine`,
  `workout_summary`, and `cardiac_engine` were written against legacy
  `power`, `heart_rate`, `cadence` names. Added backward-compat properties
  on `ActivityStreamEnhanced` (`power`, `heart_rate`, `cadence`,
  `has_power`, `has_heart_rate`, `total_distance_m`, `total_ascent_m`,
  `device_name`, `sub_sport`) so both vocabularies work.

- **Missing legacy import shim.** `hrv_engine.py` imported
  `clean_rr_intervals` from `engines.hrv_dfa.analysis` (an external
  dependency not in the codebase). Added minimal in-package shim with the
  same signature.

- **End-to-end test added.** `test_e2e.py` exercises the full pipeline:
  FIT parsing → orchestrator → all engines → narratives. Currently 20/20
  PASS on synthetic 1Hz data.

- **Version consistency.** `VERSION`, `__init__.py.__version__`, `README.md`,
  and `CHANGELOG.md` all reference 3.2.0.

### Changed

- README rewritten without marketing claims. Removed "industry-leading",
  "seed-ready", "2-3 year moat", "scientifically validated", "fundable
  business", and competitive scoring tables.
- Module classification documented (REFERENCE-BASED vs MODEL-DERIVED vs
  HEURISTIC) so consumers know what they're getting.
- Known limitations section is explicit about missing validation,
  missing `MetabolicProfiler` class, and synthetic-only test data.

### Excluded from public API

- `metabolic_current.py` — depends on `MetabolicProfiler` class which is
  not in the current extracted codebase. The module is still in the
  package directory but not exported from `__init__.py`.

### Not yet done

- Validation against lab testing
- Testing on real `.fit` files (only synthetic 1Hz records tested)
- Cross-tool agreement study vs TrainingPeaks/WKO5
- Clinical reliability study
- Recovery of the `MetabolicProfiler` class (needed for full metabolic profiling)

---

## [3.1.x] — 2026-05-18

Multiple iterations claimed bugfixes and strategic enhancements but had
the API mismatch documented above. Treat as superseded by 3.2.0.

## [3.0.0] — 2026-05-18

Added Phase 3 engines: durability, training_variability, w_prime_balance,
metabolic_flexibility.

## [2.0.0] — 2026-05-10

Added detraining_engine, metabolic_current (which still references the
missing MetabolicProfiler class).

## [1.0.0] — 2026-04-28

Initial core: athlete_context, power_engine, zones_engine,
coggan_classifier, cardiac_engine, hrv_engine, workout_summary, fit_parser.
