from engines.core.athlete_context import AthleteContext
from engines.metabolic.metabolic_current import get_current_metabolic_status
from engines.metabolic.metabolic_profiler import MetabolicProfiler


def test_metabolic_snapshot_exposes_model_metadata_and_ui_display() -> None:
    profiler = MetabolicProfiler(weight=72.0, context=AthleteContext())
    snap = profiler.generate_metabolic_snapshot({5: 950, 60: 470, 300: 340, 1200: 285, 3600: 265})
    assert snap["status"] == "success"
    assert "model_metadata" in snap
    assert "ui_display" in snap
    assert isinstance(snap["model_metadata"]["assumptions"], list)
    assert "show_values" in snap["ui_display"]


def test_metabolic_snapshot_low_confidence_recommends_masking() -> None:
    profiler = MetabolicProfiler(weight=72.0, context=AthleteContext())
    # no glycolytic anchors -> non fully expressive -> confidence capped
    snap = profiler.generate_metabolic_snapshot({300: 340, 1200: 290, 3600: 270})
    assert snap["status"] == "success"
    assert snap["confidence_score"] <= 0.40
    assert snap["ui_display"]["show_values"] is False
    assert snap["ui_display"]["reason"] == "confidence_below_threshold_use_placeholder"


def test_metabolic_current_adds_model_metadata() -> None:
    mmp = {5: 1000, 60: 500, 300: 340, 1200: 285, 3600: 265}
    history = [{"date": "2026-06-01", "tss": 80}, {"date": "2026-06-03", "tss": 75}, {"date": "2026-06-05", "tss": 90}]
    out = get_current_metabolic_status(
        historical_mmp=mmp,
        workout_history=history,
        athlete_weight_kg=72.0,
        today="2026-06-16",
    )
    assert out["status"] == "success"
    assert "model_metadata" in out
    assert 0.0 <= out["model_metadata"]["confidence_score"] <= 1.0
