"""Port of tests/integration/test_v360_pedaling_balance.py for coverage."""

from __future__ import annotations

import random
from datetime import date

import numpy as np
import pytest

from engines.io.fit_parser import ActivityStreamEnhanced
from engines.recovery.pedaling_balance import (
    PedalingBalanceReport,
    analyze_balance_trend,
    analyze_pedaling_balance,
)


@pytest.fixture(autouse=True)
def _seed() -> None:
    random.seed(42)


class TestPedalingBalancePort:
    def test_source_gating(self) -> None:
        refused = analyze_pedaling_balance(
            balance_stream=[50.0] * 1800,
            power_stream=[200.0] * 1800,
            pedaling_balance_source="single_estimated",
        )
        assert refused.data_quality == "refused_single_side"
        assert refused.avg_left_pct is None

        unknown = analyze_pedaling_balance(
            balance_stream=[49.0] * 1800,
            power_stream=[180.0] * 1800,
            pedaling_balance_source="unknown",
        )
        assert unknown.data_quality in {"good", "limited"}
        assert any("unconfirmed" in n.lower() for n in unknown.notes)

        strict = analyze_pedaling_balance(
            balance_stream=[49.0] * 1800,
            power_stream=[180.0] * 1800,
            pedaling_balance_source="unknown",
            accept_unknown_source=False,
        )
        assert strict.data_quality == "refused_single_side"

        dual = analyze_pedaling_balance(
            balance_stream=[49.5] * 1800,
            power_stream=[180.0] * 1800,
            pedaling_balance_source="dual",
        )
        assert dual.data_quality == "good"

    def test_symmetric_and_marked_asymmetry(self) -> None:
        balance = [50.0 + random.gauss(0, 1.0) for _ in range(3600)]
        power = [180.0 + random.gauss(0, 5) for _ in range(3600)]
        sym = analyze_pedaling_balance(balance, power, pedaling_balance_source="dual", ftp=250)
        assert sym.asymmetry_classification == "symmetric"
        assert sym.asymmetry_pct < 2.0
        assert sym.clinical_recommendation is None

        marked_balance = [40.0 + random.gauss(0, 1.0) for _ in range(3600)]
        marked = analyze_pedaling_balance(
            marked_balance, power, pedaling_balance_source="dual", ftp=250
        )
        assert marked.asymmetry_classification in {"moderate", "marked"}
        assert marked.dominant_leg == "right"
        assert marked.clinical_recommendation is not None

    def test_drift_and_zones(self) -> None:
        balance: list[float] = []
        n = 5400
        for i in range(n):
            progress = i / n
            balance.append(50.0 - progress * 5.0 + random.gauss(0, 0.6))
        power = [170.0 + random.gauss(0, 5) for _ in range(n)]
        drift = analyze_pedaling_balance(balance, power, pedaling_balance_source="dual", ftp=250)
        assert drift.drift_classification in {"drifting", "strong_drift"}
        assert drift.drift_direction == "rightward"
        assert drift.clinical_recommendation is not None

        zone_balance: list[float] = []
        zone_power: list[float] = []
        for _ in range(1800):
            zone_balance.append(50.0 + random.gauss(0, 1))
            zone_power.append(180 + random.gauss(0, 5))
        for _ in range(1200):
            zone_balance.append(47.0 + random.gauss(0, 1))
            zone_power.append(260 + random.gauss(0, 8))
        for _ in range(600):
            zone_balance.append(44.5 + random.gauss(0, 1.5))
            zone_power.append(320 + random.gauss(0, 10))
        zones = analyze_pedaling_balance(
            zone_balance, zone_power, pedaling_balance_source="dual", ftp=250
        )
        assert zones.balance_by_zone is not None
        assert zones.zone_shift_flag == "shifts_with_load"

    def test_insufficient_data_and_contract(self) -> None:
        no_ftp = analyze_pedaling_balance(
            [49.0] * 1800,
            [180.0] * 1800,
            pedaling_balance_source="dual",
            ftp=None,
        )
        assert no_ftp.asymmetry_classification is not None
        assert no_ftp.balance_by_zone is None

        short = analyze_pedaling_balance([49.0] * 30, [180.0] * 30, pedaling_balance_source="dual")
        assert short.data_quality == "insufficient_data"

        low_power = analyze_pedaling_balance(
            [49.0] * 3600, [50.0] * 3600, pedaling_balance_source="dual"
        )
        assert low_power.data_quality == "insufficient_data"

        nan_balance = analyze_pedaling_balance(
            [float("nan")] * 1800,
            [200.0] * 1800,
            pedaling_balance_source="dual",
        )
        assert nan_balance.data_quality == "insufficient_data"

        d = analyze_pedaling_balance(
            [49.0] * 1800,
            [180.0] * 1800,
            pedaling_balance_source="dual",
            ftp=250,
        ).to_dict()
        required = {
            "data_quality",
            "pedaling_balance_source",
            "n_total_samples",
            "n_valid_samples",
            "avg_left_pct",
            "asymmetry_classification",
            "tier",
        }
        assert required.issubset(d.keys())
        assert d["tier"] == "REFERENCE"

    def test_trend_analysis(self) -> None:
        def make_session_report(asym_pct: float, drift: float) -> PedalingBalanceReport:
            return PedalingBalanceReport(
                data_quality="good",
                pedaling_balance_source="dual",
                n_total_samples=3600,
                n_valid_samples=3500,
                avg_left_pct=50 - asym_pct / 2,
                avg_right_pct=50 + asym_pct / 2,
                asymmetry_pct=asym_pct,
                dominant_leg="right" if asym_pct > 0 else "left",
                asymmetry_classification=(
                    "symmetric"
                    if asym_pct < 4
                    else "mild"
                    if asym_pct < 10
                    else "moderate"
                ),
                first_half_left_pct=50 - asym_pct / 2 + 1,
                second_half_left_pct=50 - asym_pct / 2 - 1,
                intra_session_drift=drift,
                drift_classification=(
                    "stable"
                    if abs(drift) < 1.5
                    else "drifting"
                    if abs(drift) < 3.0
                    else "strong_drift"
                ),
                drift_direction=(
                    "stable"
                    if abs(drift) < 1.5
                    else "leftward"
                    if drift > 0
                    else "rightward"
                ),
                balance_by_zone={"z1_z2": 50 - asym_pct / 2},
            )

        worsening = [
            make_session_report(float(i), 0.5 + i * 0.2) for i in range(2, 11)
        ]
        trend = analyze_balance_trend(worsening)
        assert trend.n_endurance_sessions == 9
        assert trend.trend == "worsening"

        stable = analyze_balance_trend([make_session_report(5, 0.5) for _ in range(6)])
        assert stable.trend == "stable"

        short = analyze_balance_trend([make_session_report(5, 0.5)])
        assert short.trend is None

        mixed = [
            make_session_report(5, 1),
            make_session_report(6, 1),
            PedalingBalanceReport(
                data_quality="refused_single_side",
                pedaling_balance_source="single_estimated",
                n_total_samples=1800,
                n_valid_samples=0,
            ),
            make_session_report(7, 1),
            make_session_report(8, 1),
        ]
        filtered = analyze_balance_trend(mixed)
        assert filtered.n_endurance_sessions == 4

    def test_fit_stream_defaults(self) -> None:
        stream = ActivityStreamEnhanced(n_samples=100)
        assert hasattr(stream, "left_right_balance")
        assert np.all(np.isnan(stream.left_right_balance))
        assert stream.pedaling_balance_source == "unknown"
