"""Targeted unit tests for low-coverage engine modules — perfection hardening."""

from __future__ import annotations

import random

import pytest

from engines.io import chart_builder
from engines.metabolic.metabolic_flexibility_engine import (
    calculate_metabolic_flexibility_index,
    estimate_fat_oxidation_rate,
)
from engines.performance.durability_engine import (
    calculate_durability_index,
    calculate_np_drift,
    calculate_tte_sustainability,
    generate_durability_prescription,
    generate_hourly_decay_curve,
)
from engines.recovery.pedaling_balance import analyze_balance_trend, analyze_pedaling_balance
from engines.workouts.exporters.mrc import export_mrc
from engines.workouts.exporters.zwo import export_zwo


POWER_3H = [250] * 10800
POWER_45M = [280] * 2700


class TestDurabilityEngine:
    def test_durability_index_success_classification(self) -> None:
        result = calculate_durability_index(POWER_3H, len(POWER_3H))
        assert result["status"] == "success"
        assert result["classification"] in {"EXCELLENT", "GOOD", "FAIR", "POOR"}
        assert result["durability_index"] >= 95

    def test_durability_index_insufficient_duration(self) -> None:
        short = [200] * 600
        result = calculate_durability_index(short, len(short))
        assert result["status"] == "insufficient_duration"

    def test_durability_index_empty_power(self) -> None:
        result = calculate_durability_index([], 0)
        assert result["status"] == "insufficient_duration"

    def test_np_drift_short_session(self) -> None:
        result = calculate_np_drift([200, 210, 205], 3)
        assert result["status"] == "insufficient_duration"

    def test_np_drift_success(self) -> None:
        drift_power = [260] * 1800 + [240] * 1800
        result = calculate_np_drift(drift_power, len(drift_power))
        assert result["status"] == "success"
        assert "np_drift_pct" in result

    def test_tte_sustainability_threshold_hold(self) -> None:
        power = [300] * 1200 + [200] * 600
        result = calculate_tte_sustainability(power, 280)
        assert result["status"] == "success"
        assert result["tte_minutes"] >= 15

    def test_hourly_decay_curve(self) -> None:
        result = generate_hourly_decay_curve(POWER_3H, len(POWER_3H))
        assert result["status"] == "success"
        assert len(result["hourly_data"]) == 3

    def test_hourly_decay_too_short(self) -> None:
        result = generate_hourly_decay_curve([200] * 100, 100)
        assert result["status"] == "insufficient_duration"

    @pytest.mark.parametrize(
        "index,classification",
        [(98.0, "EXCELLENT"), (94.0, "GOOD"), (90.0, "FAIR"), (80.0, "POOR")],
    )
    def test_durability_prescription_tiers(self, index: float, classification: str) -> None:
        rx = generate_durability_prescription(index, classification)
        assert "focus" in rx
        assert "volume" in rx
        assert rx["key_sessions"]


class TestMetabolicFlexibilityEngine:
    def test_mfi_excellent(self) -> None:
        result = calculate_metabolic_flexibility_index(210, 280)
        assert result["status"] == "success"
        assert result["classification"] == "EXCELLENT"

    def test_mfi_carb_dependent(self) -> None:
        result = calculate_metabolic_flexibility_index(150, 280)
        assert result["classification"] == "CARB_DEPENDENT"

    def test_mfi_zero_vt2(self) -> None:
        result = calculate_metabolic_flexibility_index(200, 0)
        assert result["status"] == "error"

    def test_fat_oxidation_elite(self) -> None:
        result = estimate_fat_oxidation_rate(250, 70)
        assert result["status"] == "success"
        assert result["classification"] in {"ELITE", "TRAINED", "RECREATIONAL"}

    def test_fat_oxidation_invalid_weight(self) -> None:
        result = estimate_fat_oxidation_rate(200, 0)
        assert result["status"] == "error"


class TestWorkoutExporters:
  WORKOUT = {
      "name": "Perfection Test",
      "ftp_w": 300,
      "steps": [
          {"type": "warmup", "duration_s": 300, "target_pct": 0.55},
          {"type": "work", "duration_s": 120, "target_w": 320},
      ],
  }

  def test_export_mrc_structure(self) -> None:
      result = export_mrc(self.WORKOUT)
      assert result["status"] == "success"
      assert result["format"] == "mrc"
      assert "[COURSE DATA]" in result["content"]
      assert result["filename"].endswith(".mrc")

  def test_export_zwo_escapes_name(self) -> None:
      workout = dict(self.WORKOUT, name='Test & "Intervals"')
      result = export_zwo(workout)
      assert result["status"] == "success"
      assert "&amp;" in result["content"] or "&" not in result["content"].split("<name>")[1]
      assert "SteadyState" in result["content"]

  def test_export_empty_steps_still_returns_file(self) -> None:
      result = export_mrc({"name": "Empty", "steps": []})
      assert result["status"] == "success"
      assert "[END COURSE DATA]" in result["content"]


class TestPedalingBalance:
    @pytest.fixture(autouse=True)
    def _seed(self) -> None:
        random.seed(42)

    def test_single_estimated_refused(self) -> None:
        report = analyze_pedaling_balance(
            [50.0] * 300,
            [200.0] * 300,
            pedaling_balance_source="single_estimated",
        )
        assert report.data_quality == "refused_single_side"

    def test_dual_symmetric(self) -> None:
        report = analyze_pedaling_balance(
            [49.5] * 600,
            [180.0] * 600,
            pedaling_balance_source="dual",
            ftp=250,
        )
        assert report.data_quality == "good"
        assert report.avg_left_pct is not None

    def test_balance_trend_requires_sessions(self) -> None:
        trend = analyze_balance_trend([])
        assert trend.n_sessions == 0


class TestChartBuilder:
    MMP = {60: 400, 300: 320, 1200: 280}

    def test_power_duration_curve(self) -> None:
        cfg = chart_builder.chart_power_duration_curve(self.MMP, cp_model={"cp": 270, "w_prime": 20000}, ftp=250)
        assert cfg["type"] == "line_scatter"
        assert cfg["series"]

    def test_zones_distribution(self) -> None:
        cfg = chart_builder.chart_zones_distribution({"coggan": {"Z1": 20, "Z2": 50, "Z3": 30}}, system="coggan")
        assert cfg["type"] == "bar_stacked"

    def test_hrv_timeline(self) -> None:
        cfg = chart_builder.chart_hrv_timeline(
            time_seconds=[float(i * 60) for i in range(10)],
            dfa_alpha1=[0.9 - i * 0.02 for i in range(10)],
            vt1_power=200,
            vt2_power=260,
            power_series=[180 + i * 5 for i in range(10)],
        )
        assert cfg["type"] == "line_multi_axis"

    def test_training_load(self) -> None:
        from datetime import date

        cfg = chart_builder.chart_training_load(
            dates=[date(2026, 1, 1), date(2026, 1, 2)],
            ctl_values=[50, 52],
            atl_values=[45, 48],
            tsb_values=[5, 4],
        )
        assert cfg["type"] == "line_multi"

    def test_detraining_decay(self) -> None:
        cfg = chart_builder.chart_detraining_decay(
            parameters=["VO2max", "MLSS"],
            baseline_values=[65, 300],
            current_values=[62, 290],
            units=["ml/kg/min", "W"],
        )
        assert cfg["type"] == "bar_grouped"

    def test_efforts_radar(self) -> None:
        cfg = chart_builder.chart_efforts_radar(
            durations=["5s", "1min", "5min"],
            pct_ftp=[180, 120, 105],
            pct_cp=[170, 115, 100],
            pct_mlss=[160, 110, 98],
            pct_map=[150, 105, 95],
        )
        assert cfg["type"] == "radar"

    def test_phenotype_spider(self) -> None:
        cfg = chart_builder.chart_phenotype_spider({"5s": 7, "1min": 6, "FTP": 4})
        assert cfg["type"] == "radar"

    def test_cross_validation_matrix(self) -> None:
        cfg = chart_builder.chart_cross_validation_matrix(
            methods=["Mader", "Lab"],
            vt1_powers=[200, 205],
            vt2_powers=[260, 255],
        )
        assert cfg["type"] == "table"

    def test_cardiac_drift(self) -> None:
        cfg = chart_builder.chart_cardiac_drift(
            [
                {"segment": "first_half", "drift_pct": 2.5, "fitness": "EXCELLENT"},
                {"segment": "second_half", "drift_pct": 5.0, "fitness": "GOOD"},
            ]
        )
        assert cfg["type"] == "bar"

    def test_hr_kinetics(self) -> None:
        cfg = chart_builder.chart_hr_kinetics(
            time_seconds=[0, 60, 120, 180],
            hr_values=[100, 130, 145, 150],
            tau=45.0,
            steady_state_hr=155,
        )
        assert cfg["type"] == "line_scatter"

    def test_power_hr_scatter(self) -> None:
        cfg = chart_builder.chart_power_hr_scatter(
            power_values=[200, 220, 240],
            hr_values=[130, 140, 150],
            mlss_power=260,
        )
        assert cfg["type"] == "scatter"

    def test_hr_recovery(self) -> None:
        cfg = chart_builder.chart_hr_recovery(
            [{"name": "R1", "hrr_60s": 25, "hrr_120s": 40}]
        )
        assert cfg["type"] == "bar_grouped"

    def test_metabolic_combustion(self) -> None:
        cfg = chart_builder.chart_metabolic_combustion(
            power_points=[100, 150, 200, 250],
            fat_contribution=[0.8, 0.6, 0.4, 0.2],
            carb_contribution=[0.15, 0.3, 0.45, 0.55],
            anaerobic_contribution=[0.05, 0.1, 0.15, 0.25],
        )
        assert cfg["type"] == "area_stacked"
