"""Port of tests/integration/test_v500_kalman_neural.py for coverage."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from engines.core.athlete_context import AthleteContext
from engines.metabolic.bayesian_profiler import bayesian_metabolic_snapshot
from engines.metabolic.metabolic_kalman import DailyInput, MetabolicKalman, process_workout_history
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from engines.performance.mader_residual_mlp import NeuralDynamics, NeuralPowerDuration, TinyMLP

X0 = np.array([55.0, 0.40])
P0 = np.diag([5.0**2, 0.15**2])


class TestKalmanNeuralPort:
    def test_tiny_mlp(self) -> None:
        mlp = TinyMLP(n_in=3, n_hidden=8, n_out=2, seed=0)
        x = np.array([1.0, 2.0, 3.0])
        y = mlp.forward(x)
        assert y.shape == (2,)
        state = mlp.get_params()
        mlp2 = TinyMLP(3, 8, 2)
        mlp2.set_params(state)
        assert np.allclose(mlp.forward(x), mlp2.forward(x))

    def test_neural_power_duration(self) -> None:
        npd = NeuralPowerDuration()
        durs = np.array([60, 300, 600, 1200], dtype=float)
        mader_preds = np.array([400, 320, 290, 270], dtype=float)
        observed = np.array([410, 330, 295, 275], dtype=float)
        assert np.allclose(npd.predict(durs, mader_preds, vo2max=55, vlamax=0.4), mader_preds)

        result = npd.fit(durs, observed, mader_preds, vo2max=55, vlamax=0.4, reg_lambda=0.001)
        assert result.success
        trained = npd.predict(durs, mader_preds, vo2max=55, vlamax=0.4)
        assert float(np.mean((trained - observed) ** 2)) < float(np.mean((mader_preds - observed) ** 2))

        npd2 = NeuralPowerDuration()
        npd2.load_state(npd.get_state())
        assert np.allclose(trained, npd2.predict(durs, mader_preds, vo2max=55, vlamax=0.4), atol=0.1)

        small = npd.fit(durs[:2], observed[:2], mader_preds[:2], 55, 0.4)
        assert not small.success

    def test_metabolic_kalman_predict_and_update(self) -> None:
        kalman = MetabolicKalman(X0, P0, weight=72, start_date=date(2026, 1, 1))
        for day_offset in range(1, 8):
            kalman.predict(DailyInput(date=date(2026, 1, 1) + timedelta(days=day_offset)))

        rested = kalman.current_state
        assert rested.vo2max < 55.0
        assert rested.vlamax < 0.40

        trained = MetabolicKalman(X0, P0, weight=72, start_date=date(2026, 1, 1))
        for day_offset in range(1, 8):
            trained.predict(
                DailyInput(
                    date=date(2026, 1, 1) + timedelta(days=day_offset),
                    vo2max_stimulus_min=15.0,
                    neuromuscular_stimulus_min=3.0,
                )
            )
        assert trained.current_state.vo2max >= rested.vo2max

        updater = MetabolicKalman(X0, P0, weight=72, start_date=date(2026, 1, 1))
        for d in range(1, 15):
            updater.predict(DailyInput(date=date(2026, 1, 1) + timedelta(days=d)))
        pre_std = updater.current_state.vo2max_std
        updater.update([(300, 340), (600, 305), (1200, 290)])
        assert updater.current_state.vo2max_std < pre_std

    def test_process_workout_history(self) -> None:
        daily_inputs: list[DailyInput] = []
        for d in range(30):
            dt = date(2026, 3, 1) + timedelta(days=d)
            is_train = dt.weekday() in (0, 2, 4, 5)
            di = DailyInput(
                date=dt,
                vo2max_stimulus_min=12.0 if is_train else 0.0,
                threshold_stimulus_min=8.0 if is_train else 0.0,
                neuromuscular_stimulus_min=3.0 if is_train and dt.weekday() == 5 else 0.0,
            )
            if d == 15:
                di.test_anchors = [(300, 340), (600, 310), (1200, 290)]
            daily_inputs.append(di)

        traj = process_workout_history(
            daily_inputs,
            initial_vo2=55.0,
            initial_vla=0.40,
            weight=72,
            athlete_id="test_athlete",
        )
        assert len(traj.states) == 31
        assert traj.n_update_steps >= 1
        d = traj.to_dict()
        assert {"athlete_id", "n_days", "states", "final_state", "tier"}.issubset(d.keys())

    def test_neural_dynamics(self) -> None:
        nd = NeuralDynamics()
        assert nd.predict_delta(vo2max=55, vlamax=0.4, vo2_stimulus_min=10, vla_stimulus_min=3) == (0.0, 0.0)

        transitions = [
            {
                "vo2_before": 55,
                "vla_before": 0.4,
                "vo2_after": 55.3,
                "vla_after": 0.40,
                "vo2_stimulus_min": 15,
                "vla_stimulus_min": 3,
                "days_between": 7,
            },
            {
                "vo2_before": 55.3,
                "vla_before": 0.40,
                "vo2_after": 54.8,
                "vla_after": 0.39,
                "vo2_stimulus_min": 0,
                "vla_stimulus_min": 0,
                "days_between": 7,
            },
            {
                "vo2_before": 54.8,
                "vla_before": 0.39,
                "vo2_after": 55.5,
                "vla_after": 0.41,
                "vo2_stimulus_min": 20,
                "vla_stimulus_min": 5,
                "days_between": 7,
            },
            {
                "vo2_before": 55.5,
                "vla_before": 0.41,
                "vo2_after": 56.0,
                "vla_after": 0.42,
                "vo2_stimulus_min": 18,
                "vla_stimulus_min": 4,
                "days_between": 7,
            },
            {
                "vo2_before": 56.0,
                "vla_before": 0.42,
                "vo2_after": 55.2,
                "vla_after": 0.40,
                "vo2_stimulus_min": 2,
                "vla_stimulus_min": 0,
                "days_between": 14,
            },
        ]
        result = nd.fit(transitions, reg_lambda=0.01)
        assert result.success
        delta = nd.predict_delta(55, 0.4, 15, 3)
        assert abs(delta[0]) > 1e-6 or abs(delta[1]) > 1e-6
        assert "params" in nd.get_state()

    def test_full_pipeline(self) -> None:
        ctx = AthleteContext(gender="MALE", training_years=5, discipline="ROAD")
        profiler = MetabolicProfiler(weight=72, context=ctx)
        mmp = {5: 950, 30: 620, 60: 470, 300: 340, 600: 305, 1200: 290, 3600: 270}
        bay = bayesian_metabolic_snapshot(
            profiler,
            profiler._coerce_mmp_dict(mmp),
            n_samples=500,
            n_warmup=120,
        )
        assert bay.status == "success"
        assert bay.vo2max is not None and bay.vlamax is not None

        kalman = MetabolicKalman(
            x0=np.array([bay.vo2max.mean, bay.vlamax.mean]),
            P0=np.diag([bay.vo2max.std**2, bay.vlamax.std**2]),
            weight=72,
            athlete_id="pipeline_test",
            start_date=date(2026, 6, 1),
        )
        for d in range(1, 15):
            kalman.predict(
                DailyInput(
                    date=date(2026, 6, 1) + timedelta(days=d),
                    vo2max_stimulus_min=12.0 if d % 2 == 0 else 0.0,
                )
            )
        kalman.predict(
            DailyInput(
                date=date(2026, 6, 16),
                test_anchors=[(300, 345), (600, 310)],
            )
        )
        assert kalman._n_predict >= 15
        assert kalman._n_update >= 1

        npd = NeuralPowerDuration()
        mader_preds = np.array([420, 330, 300, 275], dtype=float)
        observed = np.array([410, 340, 305, 280], dtype=float)
        npd_result = npd.fit(
            np.array([60, 300, 600, 1200], dtype=float),
            observed,
            mader_preds,
            vo2max=kalman.current_state.vo2max,
            vlamax=kalman.current_state.vlamax,
        )
        assert npd_result.success
        assert kalman.get_trajectory().to_dict()["tier"] == "MODEL"
