from engines.workouts.adaptive_planner import adapt_plan


def test_adapt_plan_splits_intensity_and_volume_factors() -> None:
    reduced = adapt_plan(
        [{"target_w": 200, "duration_min": 60, "load": 80.0}],
        readiness={"readiness_score": 40},
        last_compliance={"compliance_score": 0.4},
    )
    assert reduced["reason"] == "reduce_load"
    assert reduced["intensity_factor"] == 0.85
    assert reduced["volume_factor"] == 0.65
    assert reduced["adjustment_factor"] == 0.75
    assert reduced["adapted_plan"][0]["target_w"] == 170
    assert reduced["adapted_plan"][0]["duration_min"] == 39
    assert reduced["adapted_plan"][0]["load"] == 60.0


def test_adapt_plan_downgrades_high_intensity_session_types() -> None:
    plan = [
        {"type": "vo2", "duration_min": 60, "load": 70.0},
        {"type": "threshold", "duration_min": 90, "load": 80.0},
        {"type": "endurance", "duration_min": 120, "load": 60.0},
    ]
    adapted = adapt_plan(
        plan,
        readiness={"readiness_score": 40},
        last_compliance={"compliance_score": 0.4},
    )["adapted_plan"]

    assert adapted[0]["type"] == "endurance"
    assert adapted[0]["session_type_adapted_from"] == "vo2"
    assert adapted[1]["type"] == "endurance"
    assert adapted[1]["session_type_adapted_from"] == "threshold"
    assert "session_type_adapted_from" not in adapted[2]


def test_adapt_plan_slightly_reduces_anaerobic_to_threshold() -> None:
    adapted = adapt_plan(
        [{"type": "anaerobic", "duration_min": 45, "load": 55.0}],
        readiness={"readiness_score": 55},
        last_compliance={"compliance_score": 0.65},
    )["adapted_plan"][0]
    assert adapted["type"] == "threshold"
    assert adapted["session_type_adapted_from"] == "anaerobic"


def test_adapt_plan_progression_branch() -> None:
    progressed = adapt_plan(
        [{"target_w": 200, "load": 80.0}],
        readiness={"readiness_score": 90},
        last_compliance={"compliance_score": 0.95},
    )
    assert progressed["reason"] == "small_progression"
    assert progressed["intensity_factor"] == 1.05
    assert progressed["volume_factor"] == 1.05
    assert progressed["adapted_plan"][0]["target_w"] > 200
