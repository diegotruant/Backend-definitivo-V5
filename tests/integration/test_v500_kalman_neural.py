#!/usr/bin/env python3
"""
Test: v5.0.0 — Kalman filter + Neural ODE + full pipeline
============================================================
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from datetime import date, timedelta
import numpy as np

from engines import (
    # Existing
    MetabolicProfiler, AthleteContext, bayesian_metabolic_snapshot,
    # Kalman
    MetabolicKalman, DailyInput, process_workout_history,
    # Neural ODE
    NeuralPowerDuration, NeuralDynamics, TinyMLP,
)

results = []
def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  {'✓' if ok else '✗'} {name}" + (f" — {detail}" if not ok and detail else ""))


# =============================================================================
# 1. TinyMLP basics
# =============================================================================
print("\n[1] TinyMLP forward pass")

mlp = TinyMLP(n_in=3, n_hidden=8, n_out=2, seed=0)
x = np.array([1.0, 2.0, 3.0])
y = mlp.forward(x)
check("single input → output shape", y.shape == (2,))
check("near-zero init → output near zero", np.all(np.abs(y) < 0.5), f"got {y}")

X = np.array([[1, 2, 3], [4, 5, 6]], dtype=float)
Y = mlp.forward(X)
check("batch input → correct shape", Y.shape == (2, 2))

# Serialize / restore
state = mlp.get_params()
mlp2 = TinyMLP(3, 8, 2)
mlp2.set_params(state)
check("serialize/restore identical", np.allclose(mlp.forward(x), mlp2.forward(x)))


# =============================================================================
# 2. NeuralPowerDuration — untrained = Mader passthrough
# =============================================================================
print("\n[2] NeuralPowerDuration — untrained")

npd = NeuralPowerDuration()
durs = np.array([60, 300, 600, 1200], dtype=float)
mader_preds = np.array([400, 320, 290, 270], dtype=float)

preds = npd.predict(durs, mader_preds, vo2max=55, vlamax=0.4)
check("untrained → returns Mader unchanged",
      np.allclose(preds, mader_preds))


# =============================================================================
# 3. NeuralPowerDuration — training
# =============================================================================
print("\n[3] NeuralPowerDuration — training on athlete data")

observed = np.array([410, 330, 295, 275], dtype=float)
result = npd.fit(durs, observed, mader_preds, vo2max=55, vlamax=0.4, reg_lambda=0.001)

check("training succeeds", result.success)
check("MSE improved", result.mse_after < result.mse_before,
      f"before={result.mse_before:.1f} after={result.mse_after:.1f}")
check("improvement > 0%", result.improvement_pct > 0)

# Predictions after training should be closer to observed
trained_preds = npd.predict(durs, mader_preds, vo2max=55, vlamax=0.4)
trained_mse = float(np.mean((trained_preds - observed) ** 2))
mader_mse = float(np.mean((mader_preds - observed) ** 2))
check("trained MSE < Mader MSE",
      trained_mse < mader_mse,
      f"trained={trained_mse:.1f} mader={mader_mse:.1f}")

# Serialize/restore
state = npd.get_state()
check("state has params", "params" in state)
npd2 = NeuralPowerDuration()
npd2.load_state(state)
restored_preds = npd2.predict(durs, mader_preds, vo2max=55, vlamax=0.4)
check("restored model matches",
      np.allclose(trained_preds, restored_preds, atol=0.1))

# Too few points
result_small = npd.fit(durs[:2], observed[:2], mader_preds[:2], 55, 0.4)
check("too few points → not success", not result_small.success)


# =============================================================================
# 4. MetabolicKalman — basic predict
# =============================================================================
print("\n[4] MetabolicKalman — predict (decay)")

x0 = np.array([55.0, 0.40])
P0 = np.diag([5.0**2, 0.15**2])

kalman = MetabolicKalman(x0, P0, weight=72, start_date=date(2026, 1, 1))

# 7 days of rest (no stimulus) → should decay
for day_offset in range(1, 8):
    di = DailyInput(date=date(2026, 1, 1) + timedelta(days=day_offset))
    kalman.predict(di)

state = kalman.current_state
check("VO2max decayed after 7 days rest",
      state.vo2max < 55.0,
      f"got {state.vo2max:.2f}")
check("VLamax decayed after 7 days rest",
      state.vlamax < 0.40,
      f"got {state.vlamax:.4f}")
check("uncertainty grew (vo2max_std > initial)",
      state.vo2max_std > 5.0)


# =============================================================================
# 5. MetabolicKalman — predict with stimulus
# =============================================================================
print("\n[5] MetabolicKalman — predict with stimulus (training)")

kalman2 = MetabolicKalman(x0, P0, weight=72, start_date=date(2026, 1, 1))

# 7 days of training with VO2max stimulus
for day_offset in range(1, 8):
    di = DailyInput(
        date=date(2026, 1, 1) + timedelta(days=day_offset),
        vo2max_stimulus_min=15.0,   # 15 min above VO2max threshold
        neuromuscular_stimulus_min=3.0,
    )
    kalman2.predict(di)

state2 = kalman2.current_state
check("VO2max maintained/grew with stimulus",
      state2.vo2max >= 54.5,  # should not have decayed much
      f"got {state2.vo2max:.2f}")

# Compare: trained > rested
check("trained VO2max > rested VO2max",
      state2.vo2max > state.vo2max,
      f"trained={state2.vo2max:.2f} rested={state.vo2max:.2f}")


# =============================================================================
# 6. MetabolicKalman — update with test data
# =============================================================================
print("\n[6] MetabolicKalman — update (test observation)")

kalman3 = MetabolicKalman(x0, P0, weight=72, start_date=date(2026, 1, 1))

# After some rest, state has drifted and uncertainty has grown
for d in range(1, 15):
    kalman3.predict(DailyInput(date=date(2026, 1, 1) + timedelta(days=d)))

pre_update_std = kalman3.current_state.vo2max_std

# Now a test comes in — should reduce uncertainty
test_anchors = [(300, 340), (600, 305), (1200, 290)]
kalman3.update(test_anchors)

post_update_std = kalman3.current_state.vo2max_std
check("update reduces uncertainty",
      post_update_std < pre_update_std,
      f"before={pre_update_std:.2f} after={post_update_std:.2f}")


# =============================================================================
# 7. process_workout_history convenience function
# =============================================================================
print("\n[7] process_workout_history")

daily_inputs = []
for d in range(30):
    dt = date(2026, 3, 1) + timedelta(days=d)
    # Training days: Mon/Wed/Fri/Sat
    is_train = dt.weekday() in (0, 2, 4, 5)
    
    di = DailyInput(
        date=dt,
        vo2max_stimulus_min=12.0 if is_train else 0.0,
        threshold_stimulus_min=8.0 if is_train else 0.0,
        neuromuscular_stimulus_min=3.0 if is_train and dt.weekday() == 5 else 0.0,
    )
    # Test on day 15
    if d == 15:
        di.test_anchors = [(300, 340), (600, 310), (1200, 290)]
    
    daily_inputs.append(di)

traj = process_workout_history(
    daily_inputs,
    initial_vo2=55.0, initial_vla=0.40,
    weight=72, athlete_id="test_athlete",
)

check("trajectory has 31 states (day 0 + 30 days)",
      len(traj.states) == 31,
      f"got {len(traj.states)}")
check("trajectory has updates",
      traj.n_update_steps >= 1,
      f"got {traj.n_update_steps}")
check("athlete_id preserved", traj.athlete_id == "test_athlete")

# to_dict
d = traj.to_dict()
check("trajectory to_dict has expected keys",
      {"athlete_id", "n_days", "states", "final_state", "tier"}.issubset(d.keys()))


# =============================================================================
# 8. NeuralDynamics — untrained = zero delta
# =============================================================================
print("\n[8] NeuralDynamics — untrained")

nd = NeuralDynamics()
delta = nd.predict_delta(vo2max=55, vlamax=0.4, vo2_stimulus_min=10, vla_stimulus_min=3)
check("untrained → zero delta", delta == (0.0, 0.0))


# =============================================================================
# 9. NeuralDynamics — training on transitions
# =============================================================================
print("\n[9] NeuralDynamics — training")

# Synthetic transitions: VO2max increases with stimulus, decreases without
transitions = [
    {"vo2_before": 55, "vla_before": 0.4, "vo2_after": 55.3, "vla_after": 0.40,
     "vo2_stimulus_min": 15, "vla_stimulus_min": 3, "days_between": 7},
    {"vo2_before": 55.3, "vla_before": 0.40, "vo2_after": 54.8, "vla_after": 0.39,
     "vo2_stimulus_min": 0, "vla_stimulus_min": 0, "days_between": 7},
    {"vo2_before": 54.8, "vla_before": 0.39, "vo2_after": 55.5, "vla_after": 0.41,
     "vo2_stimulus_min": 20, "vla_stimulus_min": 5, "days_between": 7},
    {"vo2_before": 55.5, "vla_before": 0.41, "vo2_after": 56.0, "vla_after": 0.42,
     "vo2_stimulus_min": 18, "vla_stimulus_min": 4, "days_between": 7},
    {"vo2_before": 56.0, "vla_before": 0.42, "vo2_after": 55.2, "vla_after": 0.40,
     "vo2_stimulus_min": 2, "vla_stimulus_min": 0, "days_between": 14},
]

result = nd.fit(transitions, reg_lambda=0.01)
check("dynamics training succeeds", result.success)
check("dynamics has transitions", result.n_transitions == 5)

# After training, predict delta should be non-zero
delta_trained = nd.predict_delta(55, 0.4, 15, 3)
check("trained dynamics gives non-zero delta",
      abs(delta_trained[0]) > 1e-6 or abs(delta_trained[1]) > 1e-6,
      f"got {delta_trained}")

# Serialize
state = nd.get_state()
check("dynamics state serializable", "params" in state)


# =============================================================================
# 10. Full pipeline: Bayesian → Kalman → Neural correction
# =============================================================================
print("\n[10] Full pipeline integration")

ctx = AthleteContext(gender="MALE", training_years=5, discipline="ROAD")
profiler = MetabolicProfiler(weight=72, context=ctx)

# Step 1: Bayesian profiler → initial state with uncertainty
mmp = {5: 950, 30: 620, 60: 470, 300: 340, 600: 305, 1200: 290, 3600: 270}
bay = bayesian_metabolic_snapshot(profiler, profiler._coerce_mmp_dict(mmp),
                                  n_samples=1000, n_warmup=300)

check("step 1: Bayesian snapshot success", bay.status == "success")

# Step 2: Initialize Kalman from Bayesian posterior
kalman = MetabolicKalman(
    x0=np.array([bay.vo2max.mean, bay.vlamax.mean]),
    P0=np.diag([bay.vo2max.std**2, bay.vlamax.std**2]),
    weight=72,
    athlete_id="pipeline_test",
    start_date=date(2026, 6, 1),
)

check("step 2: Kalman initialized from Bayesian",
      abs(kalman.current_state.vo2max - bay.vo2max.mean) < 0.01)

# Step 3: Process 14 days of training
for d in range(1, 15):
    is_train = d % 2 == 0
    di = DailyInput(
        date=date(2026, 6, 1) + timedelta(days=d),
        vo2max_stimulus_min=12.0 if is_train else 0.0,
    )
    kalman.predict(di)

check("step 3: 14 days processed",
      kalman._n_predict == 14)

# Step 4: Test day with qualified anchors
test_day = DailyInput(
    date=date(2026, 6, 16),
    test_anchors=[(300, 345), (600, 310)],
)
kalman.predict(test_day)

check("step 4: test observation applied",
      kalman._n_update >= 1)

# Step 5: Neural power-duration correction
npd = NeuralPowerDuration()
mader_preds = np.array([420, 330, 300, 275], dtype=float)
observed = np.array([410, 340, 305, 280], dtype=float)
npd_result = npd.fit(
    np.array([60, 300, 600, 1200], dtype=float),
    observed, mader_preds,
    vo2max=kalman.current_state.vo2max,
    vlamax=kalman.current_state.vlamax,
)

check("step 5: Neural PD trained", npd_result.success)

# Full trajectory
traj = kalman.get_trajectory()
check("full trajectory available",
      len(traj.states) >= 15)
check("trajectory tier is MODEL", traj.to_dict()["tier"] == "MODEL")

print("\n    Pipeline summary:")
print(f"      Bayesian init:   VO2max={bay.vo2max.mean:.1f} ± {bay.vo2max.std:.1f}")
print(f"      After 14 days:   VO2max={traj.states[-2].vo2max:.1f} ± {traj.states[-2].vo2max_std:.1f}")
print(f"      After test:      VO2max={traj.states[-1].vo2max:.1f} ± {traj.states[-1].vo2max_std:.1f}")
print(f"      Neural PD:       MSE improved {npd_result.improvement_pct:.0f}%")


# =============================================================================
# REPORT
# =============================================================================
print()
print("=" * 60)
passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f"  v5.0.0 KALMAN + NEURAL ODE: {passed}/{total} ({100*passed/total:.0f}%)")
print("=" * 60)

if passed < total:
    print("\nFailures:")
    for name, ok, detail in results:
        if not ok:
            print(f"  ✗ {name}: {detail}")
    sys.exit(1)
else:
    print("✓ All v5.0.0 checks passed.")
    sys.exit(0)
