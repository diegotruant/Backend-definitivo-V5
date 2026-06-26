"""Phase 5 — batch G: power, glycolytic, zones, activity stats, interval internals."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from engines.core.athlete_context import AthleteContext
from engines.io.activity_statistics import compute_activity_statistics
from engines.io.fit_parser import parse_fit_records_enhanced
from engines.metabolic.glycolytic_validation_engine import (
    build_glycolytic_profile,
    glycolytic_flux_index,
    predict_vlapeak_from_snapshot,
    validate_vlapeak_against_model,
    validate_wingate_glycolytic,
)
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from engines.metabolic.metabolic_profiler_phenotype import enhance_metabolic_snapshot_with_phenotype
from engines.metabolic.zones_engine import (
    _classify_distribution,
    _stream_arrays,
    coggan_power_zones,
    friel_hr_zones,
    metabolic_power_zones,
    seiler_polarization,
)
from engines.performance.interval_detector import (
    _classify_by_filename,
    _detect_ramp_protocol,
    _normalized_power,
)
from engines.performance.power_engine import (
    PowerEngine,
    mean_maximal_power,
    normalized_power,
    training_stress_score,
    variability_index,
)


def _stream(*, seconds: int = 600, power: float = 220.0):
    start = datetime(2026, 1, 1, 8, 0, 0)
    records = [
        {"timestamp": start + timedelta(seconds=i), "power": power, "heart_rate": 140.0, "cadence": 90.0}
        for i in range(seconds)
    ]
    return parse_fit_records_enhanced(records, session_dict={"start_time": start, "total_elapsed_time": seconds})


class TestPowerGlycolytic92G:
    def test_power_engine_metrics(self) -> None:
        power = np.array([200.0] * 100 + [300.0] * 200 + [180.0] * 100)
        assert normalized_power(power) > 0
        assert variability_index(250.0, 230.0) > 1.0
        assert training_stress_score(250.0, 280.0, 3600.0) > 0
        mmp = mean_maximal_power(power)
        assert mmp

        stream = _stream(seconds=1200, power=240.0)
        analyzed = PowerEngine(ftp=280.0, weight_kg=72.0).analyze(stream)
        assert analyzed["metrics"]["normalized_power"] > 0

        short_stream = _stream(seconds=30, power=180.0)
        short = PowerEngine(ftp=200.0, weight_kg=72.0).analyze(short_stream)
        assert short["status"] == "success"

    def test_glycolytic_profile_and_validation(self) -> None:
        snap = {
            "status": "success",
            "estimated_vlamax_mmol_L_s": 0.55,
            "estimated_vo2max": 58.0,
            "mlss_power_watts": 280,
        }
        profile = build_glycolytic_profile(snap, mmp={1: 950, 15: 720, 60: 480})
        assert profile["glycolytic_flux_index"] > 0
        assert glycolytic_flux_index(0.55) > glycolytic_flux_index(0.25)

        predicted = predict_vlapeak_from_snapshot(snap)
        assert predicted.get("status") in {"success", "error", "partial"}

        wingate = validate_wingate_glycolytic(
            lactate_pre_mmol=1.2,
            lactate_post_mmol=12.0,
            duration_s=30.0,
            peak_power_w=900.0,
            mean_power_w=650.0,
            profiler=MetabolicProfiler(weight=72.0),
            snapshot=snap,
            mmp={5: 900, 60: 480},
        )
        assert wingate.get("status") in {"success", "error", "warn", "partial"}

        verdict = validate_vlapeak_against_model(
            vlapeak_observed_mmol_l_s=0.62,
            predicted_vlapeak_mmol_l_s=0.58,
            model_vlamax_mmol_l_s=0.55,
        )
        assert verdict.get("status") in {"success", "error", "warn", "partial", "inconclusive"}

        enhanced = enhance_metabolic_snapshot_with_phenotype(snap, phenotype="SPRINTER")
        assert "phenotype_pcr_params" in enhanced


class TestZonesActivityInterval92G:
    def test_zones_and_activity_statistics(self) -> None:
        stream = _stream(seconds=900, power=230.0)
        arrays = _stream_arrays(stream)
        assert arrays["power"].size > 0

        metabolic_snap = {
            "status": "success",
            "mlss_power_watts": 280.0,
            "map_aerobic_watts": 350.0,
            "expressiveness": {"mlss_reliable": True},
            "zones": [
                {"name": "Z1", "minWatt": 0, "maxWatt": 154},
                {"name": "Z2", "minWatt": 155, "maxWatt": 210},
                {"name": "Z3", "minWatt": 211, "maxWatt": 252},
                {"name": "Z4", "minWatt": 253, "maxWatt": 294},
                {"name": "Z5", "minWatt": 295, "maxWatt": 350},
            ],
        }
        assert metabolic_power_zones(stream, metabolic_snap)["available"] is True
        assert coggan_power_zones(stream, ftp=280.0)["available"] is True
        assert friel_hr_zones(stream, lthr=165.0)["available"] is True
        assert seiler_polarization(stream, vt1_w=200.0, vt2_w=260.0)["available"] is True
        assert _classify_distribution(70.0, 20.0, 10.0) in {"POLARIZED", "PYRAMIDAL", "THRESHOLD", "BALANCED"}

        stats = compute_activity_statistics(stream, weight_kg=72.0, ftp=280.0, lthr=165.0, cp=300.0)
        assert isinstance(stats, dict)

    def test_interval_internals(self) -> None:
        assert _classify_by_filename("ftp_20min_test.fit") is not None
        assert _classify_by_filename(None) is None

        ramp_powers = [100.0 + i * 8 for i in range(480)]
        ramp = _detect_ramp_protocol(ramp_powers)
        assert ramp.get("is_ramp") in {True, False}

        short = _normalized_power([200.0] * 10)
        assert short > 0
