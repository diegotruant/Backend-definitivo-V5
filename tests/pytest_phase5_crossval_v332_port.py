"""Ports: test_cross_validation.py + test_v332_features.py for branch coverage."""

from __future__ import annotations

from datetime import date, timedelta

from engines.core.athlete_context import AthleteContext
from engines.core.tiers import mask_low_confidence, should_display
from engines.metabolic.cross_validation_engine import cross_validate_metabolic_profile
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from engines.performance.mmp_quality import analyze_mmp_quality, clean_mmp, filter_mmp_by_window


GOOD_MMP = {
    "Omar": (70, {5: 661, 15: 527, 30: 438, 60: 401, 120: 390, 300: 352, 600: 302, 1200: 288, 1800: 279, 3600: 242}),
    "Alessio": (56, {5: 859, 15: 731, 30: 584, 60: 463, 120: 331, 300: 270, 600: 239, 1200: 227, 1800: 216, 3600: 202}),
}


def _fit(weight: int, mmp: dict):
    prof = MetabolicProfiler(weight=weight)
    snap = prof.generate_metabolic_snapshot(mmp, expected_eta=0.23)
    unmasked = snap["unmasked_estimates"]
    return prof, snap, unmasked["estimated_vo2max"], unmasked["estimated_vlamax_mmol_L_s"]


class TestCrossValidationPort:
    def test_coherent_profiles(self) -> None:
        for name, (w, mmp) in GOOD_MMP.items():
            _, snap, _, _ = _fit(w, mmp)
            cv = snap["cross_validation"]
            assert cv["severity"] != "severe", name
            assert cv["coherence_penalty"] <= 0.25

    def test_degenerate_and_edge_cases(self) -> None:
        adrian_mmp = {5: 700, 15: 639, 30: 470, 60: 386, 120: 369, 300: 351, 600: 305, 1200: 283, 1800: 272, 3600: 265}
        _, snap, vo2, vla = _fit(88, adrian_mmp)
        assert vo2 > 40.0
        assert vla < 0.9
        assert snap["cross_validation"]["coherent"]

        prof = MetabolicProfiler(weight=88)
        cv_bad = cross_validate_metabolic_profile(prof, adrian_mmp, vo2max=30.0, vlamax=1.46, eta_base=0.23)
        assert not cv_bad.coherent
        assert cv_bad.coherence_penalty >= 0.4

        prof60 = MetabolicProfiler(weight=60)
        mmp_sub = {5: 987, 15: 694, 30: 498, 60: 439, 120: 307, 300: 260, 600: 246, 1200: 175, 1800: 165, 3600: 150}
        _, _, vo2_s, vla_s = _fit(60, mmp_sub)
        cv_sub = cross_validate_metabolic_profile(prof60, mmp_sub, vo2_s, vla_s, eta_base=0.23)
        assert not cv_sub.coherent

        mmp_short = {5: 900, 15: 700, 60: 450}
        cv_short = cross_validate_metabolic_profile(prof60, mmp_short, 55, 0.5)
        assert isinstance(cv_short.coherent, bool)
        assert cv_short.to_dict()["tier"] == "MODEL"


class TestV332MmpQualityPort:
    def test_quality_detection_and_cleaning(self) -> None:
        plateau = analyze_mmp_quality({60: 400, 120: 350, 600: 300, 720: 300, 1200: 300, 1800: 280})
        assert any(i.category == "identical_plateau" for i in plateau.issues)

        sprinty = analyze_mmp_quality({5: 1500, 60: 600, 300: 380, 1200: 280, 3600: 260})
        assert any(i.category == "sprint_outlier" for i in sprinty.issues)

        non_mono = analyze_mmp_quality({60: 300, 120: 320})
        assert any(i.category == "non_monotonic" for i in non_mono.issues)

        samples = [
            {"duration_s": 600, "power_w": 320, "filename": "long-ride.fit", "date": "2026-05-10"},
            {"duration_s": 720, "power_w": 315, "filename": "long-ride.fit", "date": "2026-05-10"},
            {"duration_s": 900, "power_w": 310, "filename": "long-ride.fit", "date": "2026-05-10"},
            {"duration_s": 1200, "power_w": 305, "filename": "long-ride.fit", "date": "2026-05-10"},
            {"duration_s": 1800, "power_w": 295, "filename": "long-ride.fit", "date": "2026-05-10"},
            {"duration_s": 3600, "power_w": 280, "filename": "long-ride.fit", "date": "2026-05-10"},
        ]
        rolling = analyze_mmp_quality({60: 400, 300: 350, 600: 320, 720: 315, 1200: 305, 3600: 280}, samples)
        assert any(i.category == "rolling_window_redundant" for i in rolling.issues)

        dirty_mmp = {5: 950, 60: 470, 300: 330, 600: 305, 720: 305, 900: 305, 1200: 295, 3600: 270}
        dirty_samples = [
            {"duration_s": 5, "power_w": 950, "filename": "a.fit", "date": "2026-04-01"},
            {"duration_s": 60, "power_w": 470, "filename": "a.fit", "date": "2026-04-01"},
            {"duration_s": 300, "power_w": 330, "filename": "b.fit", "date": "2026-04-15"},
        ] + samples
        clean, audit = clean_mmp(dirty_mmp, dirty_samples)
        assert audit["cleaned_anchors"] < audit["original_anchors"]
        assert 5 in clean

    def test_profiler_clean_and_window_filter(self) -> None:
        ctx = AthleteContext(gender="MALE", training_years=5, discipline="ROAD")
        profiler = MetabolicProfiler(weight=72, context=ctx)
        dirty_mmp = {5: 950, 60: 470, 300: 330, 600: 305, 720: 305, 1200: 295, 3600: 270}
        dirty_samples = [
            {"duration_s": 5, "power_w": 950, "filename": "a.fit", "date": "2026-04-01"},
            {"duration_s": 60, "power_w": 470, "filename": "a.fit", "date": "2026-04-01"},
            {"duration_s": 600, "power_w": 305, "filename": "long.fit", "date": "2026-05-10"},
            {"duration_s": 1200, "power_w": 295, "filename": "long.fit", "date": "2026-05-10"},
        ]
        snap = profiler.generate_metabolic_snapshot(dirty_mmp, mmp_samples=dirty_samples, clean_mmp_first=True)
        assert "mmp_quality" in snap
        snap_plain = profiler.generate_metabolic_snapshot(dirty_mmp)
        assert "mmp_quality" not in snap_plain

        today = date(2026, 5, 20)
        samples = [
            {"duration_s": 60, "power_w": 450, "date": "2026-05-15"},
            {"duration_s": 300, "power_w": 350, "date": "2026-05-01"},
            {"duration_s": 600, "power_w": 320, "date": "2025-11-01"},
        ]
        mmp_90d, kept = filter_mmp_by_window(samples, today=today, window_days=90)
        assert set(mmp_90d.keys()) == {60, 300}
        assert len(kept) == 2

        mmp_empty, _ = filter_mmp_by_window([{"duration_s": 60, "power_w": 400, "date": "2025-01-01"}], today=today)
        assert len(mmp_empty) == 0

    def test_display_gating(self) -> None:
        assert should_display(0.8) is True
        assert should_display(0.2) is False
        masked = mask_low_confidence(
            {"estimated_vo2max": 55.0, "confidence_score": 0.2},
            value_fields=["estimated_vo2max"],
            threshold=0.5,
        )
        assert masked.get("estimated_vo2max") is None or masked.get("estimated_vo2max") == "—"
