from engines.adaptive_load.trend import calculate_load_trend
from engines.performance.ability_profile import build_ability_profile
from engines.readiness.readiness_engine import compute_load_risk, compute_readiness_today
from engines.workouts.recommendation_engine import recommend_workout


def test_readiness_reports_missing_inputs_metadata() -> None:
    out = compute_readiness_today(load_state=None, hrv_status=None, sleep_status=None, subjective=None)
    meta = out.get("model_metadata", {})
    assert out["status"] == "success"
    assert "load_state" in meta.get("missing_inputs", [])
    assert "hrv_status" in meta.get("missing_inputs", [])
    assert meta.get("confidence_score", 0) <= 0.55


def test_load_risk_cold_start_flag_present() -> None:
    out = compute_load_risk({"acute_load": 0.0, "chronic_load": 0.0})
    meta = out.get("model_metadata", {})
    assert out["risk"] in {"high", "moderate", "detraining", "low"}
    assert "cold_start_low_chronic_load" in meta.get("quality_flags", [])


def test_recommendation_blocks_when_cp_missing() -> None:
    out = recommend_workout({"weight_kg": 72.0}, readiness={"readiness_score": 82})
    assert out["status"] == "insufficient_profile"
    assert out["recommendation"]["next_step"] == "provide_cp_or_ftp"
    assert out.get("recommendation", {}).get("workout") is None


def test_ability_profile_hides_wkg_without_weight() -> None:
    out = build_ability_profile({"mmp": {5: 1000, 60: 500, 300: 350, 1200: 280}})
    assert out["status"] == "success"
    assert out["derived_w_kg"]["5s"] is None
    assert "weight_kg" in out.get("model_metadata", {}).get("missing_inputs", [])


def test_trend_insufficient_data_has_cold_start_metadata() -> None:
    out = calculate_load_trend([{"session_load": 45.0} for _ in range(5)], current_session_load=44.0)
    assert out["status"] == "insufficient_data"
    assert "cold_start" in out.get("model_metadata", {}).get("quality_flags", [])
