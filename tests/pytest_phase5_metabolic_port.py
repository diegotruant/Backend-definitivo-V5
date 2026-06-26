"""Port of tests/integration/test_metabolic_profiler.py for coverage."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from engines.core.athlete_context import AthleteContext
from engines.metabolic.detraining_engine import apply_detraining_model, calculate_ctl_atl_tsb
from engines.metabolic.mader_constants import MaderConstants
from engines.metabolic.metabolic_current import get_current_metabolic_status
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from engines.metabolic.metabolic_profiler_phenotype import enhance_metabolic_snapshot_with_phenotype

MMP = {
    5: 1100,
    15: 900,
    30: 700,
    60: 520,
    180: 380,
    300: 340,
    600: 310,
    1200: 295,
    1800: 285,
    3600: 270,
}


@pytest.fixture
def profiler() -> MetabolicProfiler:
    ctx = AthleteContext(gender="MALE", training_years=5, body_fat_pct=12.0, discipline="ROAD")
    return MetabolicProfiler(weight=72.0, context=ctx)


class TestMetabolicProfilerPort:
    def test_instantiate(self, profiler: MetabolicProfiler) -> None:
        assert profiler.weight == 72.0
        assert isinstance(profiler.const, MaderConstants)
        assert profiler.active_muscle_mass > 0

    def test_generate_snapshot(self, profiler: MetabolicProfiler) -> None:
        snapshot = profiler.generate_metabolic_snapshot(MMP)
        assert snapshot.get("status") == "success"
        required = {
            "estimated_vo2max",
            "estimated_vlamax_mmol_L_s",
            "metabolic_phenotype",
            "mlss_power_watts",
            "fatmax_power_watts",
            "map_aerobic_watts",
            "confidence_score",
            "zones",
            "combustion_curve",
        }
        assert required.issubset(snapshot.keys())
        assert 40 <= snapshot["estimated_vo2max"] <= 90
        assert snapshot["mlss_power_watts"] > snapshot["fatmax_power_watts"]

    def test_insufficient_mmp(self, profiler: MetabolicProfiler) -> None:
        bad = profiler.generate_metabolic_snapshot({60: 300, 300: 250})
        assert bad.get("status") == "error"

    def test_phenotype_enhancement(self, profiler: MetabolicProfiler) -> None:
        snapshot = profiler.generate_metabolic_snapshot(MMP)
        enhanced = enhance_metabolic_snapshot_with_phenotype(snapshot.copy(), phenotype="ALL_ROUNDER")
        assert "phenotype_pcr_params" in enhanced
        assert "energy_contributions" in enhanced

    def test_metabolic_current_and_detraining(self, profiler: MetabolicProfiler) -> None:
        today = date.today()
        workout_history = [
            {"date": today - timedelta(days=30 - i), "tss": 70 + (i % 7) * 10}
            for i in range(30)
        ]
        current = get_current_metabolic_status(
            historical_mmp=MMP,
            workout_history=workout_history,
            athlete_weight_kg=72.0,
            athlete_context=None,
        )
        assert isinstance(current, dict)
        assert current.get("status") == "success"

        snapshot = profiler.generate_metabolic_snapshot(MMP)
        tl = calculate_ctl_atl_tsb(workout_history, today)
        assert "ctl" in tl
        decayed = apply_detraining_model(
            baseline_snapshot=snapshot,
            workout_history=workout_history,
            today=today,
        )
        assert isinstance(decayed, dict)
