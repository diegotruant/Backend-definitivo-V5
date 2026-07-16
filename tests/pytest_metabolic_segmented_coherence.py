"""Coherence contracts for the two-stage metabolic snapshot.

The segmented path combines an aerobic-domain VO2max with a full-curve
VLamax. Every derived field exposed to clients must therefore be rebuilt from
that final parameter pair rather than copied from either intermediate stage.
"""

from __future__ import annotations

import pytest

from engines.core.athlete_context import AthleteContext
from engines.metabolic.cross_validation_engine import cross_validate_metabolic_profile
from engines.metabolic.metabolic_profiler import MetabolicProfiler


CTX = AthleteContext(gender="MALE", training_years=10, discipline="ROAD")
BIMODAL_MMP = {5: 1100, 15: 1000, 60: 520, 300: 340, 1200: 270, 3600: 240}


def _profiler() -> MetabolicProfiler:
    return MetabolicProfiler(weight=72.0, context=CTX)


def test_segmented_derived_outputs_match_final_parameter_pair() -> None:
    profiler = _profiler()
    snap = profiler.generate_metabolic_snapshot_segmented(BIMODAL_MMP)

    assert snap["status"] == "success"
    vo2 = float(snap["estimated_vo2max"])
    vlamax = float(snap["estimated_vlamax_mmol_L_s"])
    eta = float(snap["context_used"]["resolved_eta"])

    expected_mlss, expected_fatmax, *_ = profiler._calculate_curves(vo2, vlamax, eta)
    expected_map = profiler._map_estimate(vo2, eta)

    assert snap["mlss_power_watts"] == pytest.approx(round(expected_mlss, 1), abs=0.1)
    assert snap["fatmax_power_watts"] == pytest.approx(round(expected_fatmax, 1), abs=0.1)
    assert snap["map_aerobic_watts"] == pytest.approx(round(expected_map, 1), abs=0.1)

    unmasked = snap["unmasked_estimates"]
    assert unmasked["estimated_vo2max"] == pytest.approx(vo2, abs=0.1)
    assert unmasked["estimated_vlamax_mmol_L_s"] == pytest.approx(vlamax, abs=0.0001)
    assert unmasked["mlss_power_watts"] == pytest.approx(round(expected_mlss, 1), abs=0.1)
    assert unmasked["fatmax_power_watts"] == pytest.approx(round(expected_fatmax, 1), abs=0.1)


def test_segmented_uses_full_curve_expressiveness_and_rebuilds_glycolytic_profile() -> None:
    snap = _profiler().generate_metabolic_snapshot_segmented(BIMODAL_MMP)

    reliability = snap["expressiveness"]["reliability"]
    assert reliability == {
        "vlamax": True,
        "vo2max": True,
        "mlss": True,
        "fatmax": True,
    }
    assert snap["expressiveness"]["fully_expressive"] is True

    glycolytic = snap["glycolytic_profile"]
    assert glycolytic["status"] == "success"
    assert glycolytic["estimated_vlamax_mmol_l_s"] == pytest.approx(
        float(snap["estimated_vlamax_mmol_L_s"]), abs=0.0001
    )
    predicted = glycolytic["predicted_vlapeak"]
    assert predicted["predicted_vlapeak_mmol_l_s"] == pytest.approx(
        float(snap["estimated_vlamax_mmol_L_s"]), abs=0.0001
    )


def test_segmented_cross_validation_is_recomputed_from_final_pair() -> None:
    profiler = _profiler()
    snap = profiler.generate_metabolic_snapshot_segmented(BIMODAL_MMP)

    vo2 = float(snap["estimated_vo2max"])
    vlamax = float(snap["estimated_vlamax_mmol_L_s"])
    eta = float(snap["context_used"]["resolved_eta"])
    expected = cross_validate_metabolic_profile(
        profiler,
        BIMODAL_MMP,
        vo2,
        vlamax,
        eta_base=eta,
    ).to_dict()

    assert snap["cross_validation"] == expected


def test_segmented_confidence_is_conservative_across_both_stages() -> None:
    snap = _profiler().generate_metabolic_snapshot_segmented(BIMODAL_MMP)

    detail = snap["segmented_detail"]
    assert detail["aerobic_stage_status"] == "success"
    assert detail["full_curve_stage_status"] == "success"
    assert snap["confidence_score"] <= detail["aerobic_stage_confidence"]
    assert snap["confidence_score"] <= detail["full_curve_stage_confidence"]
    assert detail["confidence_strategy"] == "minimum_of_stage_scores"


def test_segmented_does_not_report_success_when_full_curve_stage_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profiler = _profiler()
    original = profiler.generate_metabolic_snapshot
    calls = 0

    def staged_snapshot(mmp_raw, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 1:
            return original(mmp_raw, **kwargs)
        return {"status": "error", "message": "synthetic full-curve failure"}

    monkeypatch.setattr(profiler, "generate_metabolic_snapshot", staged_snapshot)
    snap = profiler.generate_metabolic_snapshot_segmented(BIMODAL_MMP)

    assert snap["status"] == "error"
    assert snap["error_code"] == "segmented_full_curve_fit_failed"
    assert snap["segmented_detail"]["aerobic_stage_status"] == "success"
    assert snap["segmented_detail"]["full_curve_stage_status"] == "error"
