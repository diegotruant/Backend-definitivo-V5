from datetime import date

from engines.metabolic.team_learning_engine import (
    TeamCalibrationModel,
    ValidationEvent,
    validation_events_from_prediction_and_lab,
)


def _event(athlete, predicted, measured, phenotype="climber"):
    return ValidationEvent(
        athlete_id=athlete,
        team_id="wt_demo",
        parameter="mlss",
        predicted_value=predicted,
        measured_value=measured,
        test_date=date(2026, 6, 1),
        model_version="v5",
        protocol="mader_lactate",
        phenotype=phenotype,
        data_depth_score=0.9,
        measurement_confidence=0.95,
    )


def test_team_calibration_learns_bounded_mlss_bias():
    # Model historically overestimates MLSS by ~15 W for this team/phenotype.
    events = [
        _event("r1", 385, 370),
        _event("r2", 372, 360),
        _event("r3", 398, 382),
        _event("r4", 360, 347),
        _event("r5", 410, 394),
    ]
    model = TeamCalibrationModel.fit(events, team_id="wt_demo")

    res = model.correction_for(
        "mlss",
        400,
        athlete_id="new_rider",
        phenotype="climber",
        data_depth_score=0.9,
    )

    assert res["applied"] is True
    assert res["correction"] < 0
    assert abs(res["correction"]) <= res["cap"]
    assert res["corrected_value"] < 400
    assert res["stats"]["team"]["n"] == 5


def test_athlete_specific_bias_dominates_when_available():
    events = [
        _event("r1", 385, 370),
        _event("r1", 390, 372),
        _event("r2", 372, 368),
        _event("r3", 398, 394),
        _event("r4", 360, 356),
        _event("r5", 410, 406),
    ]
    model = TeamCalibrationModel.fit(events, team_id="wt_demo")
    athlete = model.correction_for("mlss", 400, athlete_id="r1", phenotype="climber")
    team_only = model.correction_for("mlss", 400, athlete_id="unknown", phenotype="climber")

    assert athlete["correction"] < team_only["correction"]
    assert any(c["scope"] == "athlete" for c in athlete["components"])


def test_serialization_round_trip_and_snapshot_calibration():
    model = TeamCalibrationModel.fit([
        _event("r1", 385, 370),
        _event("r2", 372, 360),
        _event("r3", 398, 382),
        _event("r4", 360, 347),
        _event("r5", 410, 394),
    ], team_id="wt_demo")
    restored = TeamCalibrationModel.from_dict(model.to_dict())
    out = restored.calibrate_snapshot(
        {"status": "success", "mlss_power_watts": 400, "estimated_vo2max": 78.0, "phenotype": "climber"},
        athlete_id="new_rider",
        data_depth_score=0.9,
    )

    assert out["mlss_power_watts"] < 400
    assert out["raw_mlss_power_watts"] == 400
    assert "team_calibration" in out


def test_validation_events_helper_maps_prediction_and_lab_keys():
    events = validation_events_from_prediction_and_lab(
        athlete_id="r1",
        team_id="wt_demo",
        predicted_snapshot={"mlss_power_watts": 385, "estimated_vo2max": 78.0},
        measured={"measured_mlss": 370, "vo2max_ml_kg_min": 76.5},
        test_date="2026-06-01",
        protocol="mader_lactate",
        phenotype="climber",
    )

    assert {e.parameter for e in events} == {"mlss", "vo2max"}
    assert next(e for e in events if e.parameter == "mlss").error_abs == -15
