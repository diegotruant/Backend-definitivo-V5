from __future__ import annotations

from datetime import date

from api.services.mmp_publication_gate import evaluate_mmp_gate
from engines.performance import mmp_aggregator


def _entry(
    duration_s: int,
    power_w: float,
    ride_id: str,
    ride_date: str = "2026-07-01",
    reliability: float = 0.90,
):
    return {
        "duration_s": duration_s,
        "power_w": power_w,
        "ride_id": ride_id,
        "ride_date": ride_date,
        "reliability": reliability,
    }


def _publication_grade_curve():
    return {
        "5": _entry(5, 1000, "ride-sprint"),
        "30": _entry(30, 700, "ride-glycolytic"),
        "180": _entry(180, 500, "ride-vo2-a"),
        "300": _entry(300, 460, "ride-vo2-b"),
        "1200": _entry(1200, 350, "ride-threshold-a"),
        "1800": _entry(1800, 330, "ride-threshold-b"),
    }


def test_update_power_curve_keeps_best_value_and_provenance(monkeypatch):
    monkeypatch.setattr(
        mmp_aggregator,
        "extract_ride_curve",
        lambda _power: {5: 950.0, 300: 410.0},
    )
    stored = {
        "5": _entry(5, 900.0, "old-sprint", "2026-06-01"),
        "300": _entry(300, 400.0, "old-vo2", "2026-06-01"),
    }

    result = mmp_aggregator.update_power_curve(
        [200.0] * 600,
        date(2026, 7, 10),
        stored_curve=stored,
        ride_id="new-ride",
        weight_kg=72.0,
        enforce_quality_gate=False,
    )

    assert result.curve[5]["power_w"] == 950.0
    assert result.curve[5]["ride_id"] == "new-ride"
    assert result.curve[300]["power_w"] == 410.0
    assert len(result.improvements) == 2
    assert result.profile_should_refresh is True


def test_update_power_curve_does_not_replace_a_better_stored_anchor(monkeypatch):
    monkeypatch.setattr(
        mmp_aggregator,
        "extract_ride_curve",
        lambda _power: {5: 850.0},
    )
    stored = {"5": _entry(5, 900.0, "old-sprint", "2026-06-01")}

    result = mmp_aggregator.update_power_curve(
        [200.0] * 30,
        date(2026, 7, 10),
        stored_curve=stored,
        ride_id="slower-ride",
        weight_kg=72.0,
        enforce_quality_gate=False,
    )

    assert result.curve[5]["power_w"] == 900.0
    assert result.curve[5]["ride_id"] == "old-sprint"
    assert result.improvements == []
    assert result.profile_should_refresh is False


def test_update_power_curve_rejects_non_monotonic_candidate(monkeypatch):
    monkeypatch.setattr(
        mmp_aggregator,
        "extract_ride_curve",
        lambda _power: {5: 900.0, 300: 950.0},
    )

    result = mmp_aggregator.update_power_curve(
        [200.0] * 600,
        date(2026, 7, 10),
        stored_curve={},
        ride_id="bad-ride",
        weight_kg=72.0,
        enforce_quality_gate=False,
    )

    assert 5 in result.curve
    assert 300 not in result.curve
    assert result.rejected[0]["duration_s"] == 300
    assert "physically impossible" in result.rejected[0]["reason"]


def test_expired_profile_critical_anchor_triggers_refresh(monkeypatch):
    monkeypatch.setattr(mmp_aggregator, "extract_ride_curve", lambda _power: {})
    stored = {"300": _entry(300, 410.0, "old-ride", "2026-01-01")}

    result = mmp_aggregator.update_power_curve(
        [0.0] * 600,
        date(2026, 7, 10),
        stored_curve=stored,
        ride_id="empty-ride",
        weight_kg=72.0,
        window_days=90,
        today=date(2026, 7, 10),
        enforce_quality_gate=False,
    )

    assert result.curve == {}
    assert result.expired[0]["duration_s"] == 300
    assert result.profile_should_refresh is True


def test_complete_fresh_diverse_curve_is_published():
    assessment = evaluate_mmp_gate(
        _publication_grade_curve(),
        as_of="2026-07-14",
    )

    assert assessment.lifecycle_status == "published"
    assert assessment.profile_eligible is True
    assert assessment.frontend_visibility == "show"
    assert assessment.coverage == {
        "sprint": "present",
        "glycolytic": "present",
        "vo2": "present",
        "threshold": "present",
    }
    assert assessment.source_activity_count == 6
    assert assessment.quality["classification"] == "good"


def test_partial_threshold_evidence_is_provisional_not_publishable():
    curve = _publication_grade_curve()
    del curve["1800"]

    assessment = evaluate_mmp_gate(curve, as_of="2026-07-14")

    assert assessment.coverage["threshold"] == "partial"
    assert assessment.lifecycle_status == "provisional"
    assert assessment.profile_eligible is False
    assert assessment.frontend_visibility == "coach_preview"


def test_missing_threshold_band_remains_collecting():
    curve = _publication_grade_curve()
    del curve["1200"]
    del curve["1800"]

    assessment = evaluate_mmp_gate(curve, as_of="2026-07-14")

    assert assessment.coverage["threshold"] == "missing"
    assert assessment.lifecycle_status == "collecting"
    assert assessment.profile_eligible is False
    assert any(
        "threshold duration band is missing" in reason
        for reason in assessment.decision_reasons
    )


def test_non_monotonic_curve_is_invalid():
    curve = _publication_grade_curve()
    curve["300"] = _entry(300, 550, "ride-bad-vo2")

    assessment = evaluate_mmp_gate(curve, as_of="2026-07-14")

    assert assessment.lifecycle_status == "invalid"
    assert assessment.profile_eligible is False
    assert assessment.frontend_visibility == "hidden"
    assert assessment.quality["blocking_issues"]


def test_formerly_published_stale_curve_becomes_degraded():
    curve = _publication_grade_curve()
    for entry in curve.values():
        entry["ride_date"] = "2026-01-01"

    assessment = evaluate_mmp_gate(
        curve,
        as_of="2026-07-14",
        previous_lifecycle_status="published",
    )

    assert assessment.lifecycle_status == "degraded"
    assert assessment.profile_stale is True
    assert assessment.profile_eligible is False
    assert assessment.stale_durations


def test_activity_count_alone_cannot_publish_curve():
    curve = _publication_grade_curve()
    for entry in curve.values():
        entry["ride_id"] = "same-activity"

    assessment = evaluate_mmp_gate(curve, as_of="2026-07-14")

    assert assessment.source_activity_count == 1
    assert assessment.lifecycle_status == "collecting"
    assert assessment.profile_eligible is False
    assert any(
        "independent source activities" in reason
        for reason in assessment.decision_reasons
    )


def test_missing_provenance_dates_prevent_publication():
    curve = _publication_grade_curve()
    curve["1200"]["ride_date"] = ""

    assessment = evaluate_mmp_gate(curve, as_of="2026-07-14")

    assert assessment.lifecycle_status != "published"
    assert assessment.profile_eligible is False
    assert 1200 in assessment.missing_date_durations
