from datetime import datetime, timedelta

from engines.adaptive_load.models import AthleteLoadProfile, DailyStatus
from engines.adaptive_load.orchestrator import build_adaptive_load_report
from engines.io.fit_parser import parse_fit_records_enhanced


def test_adaptive_load_report_smoke() -> None:
    start = datetime(2026, 1, 1, 8, 0, 0)
    records = []
    for i in range(900):
        records.append(
            {
                "timestamp": start + timedelta(seconds=i),
                "power": 220,
                "heart_rate": 145 + (i / 900) * 8,
                "cadence": 90,
                "distance": float(i * 8),
                "core_body_temperature": 37.8 + (i / 900) * 0.9,
                "rr_intervals": [800.0, 810.0],
            }
        )

    stream = parse_fit_records_enhanced(
        records,
        session_dict={
            "sport": "cycling",
            "start_time": start,
            "total_elapsed_time": 900,
        },
    )
    workout_summary = {
        "stream_metadata": {
            "sport": "cycling",
            "duration_s": 900,
            "has_power": True,
            "has_hr": True,
            "has_rr": True,
        },
        "sections": {
            "power": {
                "status": "success",
                "metrics": {
                    "duration_s": 900,
                    "tss": 22.0,
                    "intensity_factor": 0.78,
                    "normalized_power": 220.0,
                    "work_kj": 198.0,
                },
            },
            "cardiac": {"status": "success"},
        },
        "headline": {
            "worst_cardiac_drift_pct": 4.0,
            "worst_aerobic_decoupling_pct": 5.0,
        },
    }

    report = build_adaptive_load_report(
        stream=stream,
        workout_summary=workout_summary,
        athlete_profile=AthleteLoadProfile(weight_kg=72.0, ftp=285.0, hr_max=188.0, hr_rest=45.0),
        daily_status=DailyStatus(
            morning_hrv_lnrmssd=4.25,
            baseline_hrv_lnrmssd=4.30,
            morning_rhr=47,
            baseline_rhr=45,
            morning_temp_c=36.6,
            baseline_temp_c=36.45,
            sleep_score=78,
            soreness=2,
            stress=2,
            mood=4,
        ),
        history=[{"session_load": 45 + (i % 20)} for i in range(42)],
    )

    assert report["status"] == "success"
    assert report["headline"]["session_load_score"] is not None
    assert report["sections"]["readiness"]["available"] is True
    assert report["sections"]["recommendation"]["status"] in {"green", "yellow", "red", "blue"}
