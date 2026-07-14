from __future__ import annotations

from datetime import date

from api.schemas import TwinStateBuildRequest, TwinStateUpdateRideRequest
from api.services.twin_service import TwinService
from tests._fixtures import twin_build_payload


def _entry(duration_s: int, power_w: float, ride_id: str) -> dict:
    return {
        "duration_s": duration_s,
        "power_w": power_w,
        "ride_id": ride_id,
        "ride_date": date.today().isoformat(),
        "reliability": 0.90,
    }


def _publication_grade_curve() -> dict:
    return {
        "5": _entry(5, 1000, "ride-sprint"),
        "30": _entry(30, 700, "ride-glycolytic"),
        "180": _entry(180, 500, "ride-vo2-a"),
        "300": _entry(300, 460, "ride-vo2-b"),
        "1200": _entry(1200, 350, "ride-threshold-a"),
        "1800": _entry(1800, 330, "ride-threshold-b"),
    }


def _snapshot(vo2max: float) -> dict:
    return {
        "status": "success",
        "estimated_vo2max": vo2max,
        "estimated_vlamax_mmol_L_s": 0.42,
        "mlss_power_watts": 285.0,
        "fatmax_power_watts": 190.0,
        "map_aerobic_watts": 390.0,
        "confidence_score": 0.82,
    }


def _built_state() -> dict:
    return TwinService().build(TwinStateBuildRequest(payload=twin_build_payload()))


def test_automatic_profile_refresh_is_blocked_for_incomplete_curve() -> None:
    state = _built_state()
    previous_snapshot = dict(state.get("metabolic_snapshot") or {})
    req = TwinStateUpdateRideRequest(
        twin_state=state,
        ingest_result={
            "curve": {"300": _entry(300, 460, "ride-only")},
            "profile_should_refresh": True,
        },
        metabolic_snapshot=_snapshot(61.0),
        ride_id="ride-only",
    )

    updated = TwinService().update_from_ride(req)

    assert updated.get("metabolic_snapshot") == previous_snapshot
    assert updated["event_log"][-1]["profile_refreshed"] is False
    assert updated["rolling_power_curve"]["300"]["ride_id"] == "ride-only"


def test_automatic_profile_refresh_is_allowed_for_published_curve() -> None:
    state = _built_state()
    req = TwinStateUpdateRideRequest(
        twin_state=state,
        ingest_result={
            "curve": _publication_grade_curve(),
            "profile_should_refresh": True,
        },
        metabolic_snapshot=_snapshot(61.0),
        ride_id="ride-threshold-b",
    )

    updated = TwinService().update_from_ride(req)

    assert updated["metabolic_snapshot"]["estimated_vo2max"] == 61.0
    assert updated["event_log"][-1]["profile_refreshed"] is True


def test_explicit_profile_sync_keeps_existing_behavior() -> None:
    state = _built_state()
    req = TwinStateUpdateRideRequest(
        twin_state=state,
        ingest_result={
            "curve": {"300": _entry(300, 460, "ride-only")},
            "profile_should_refresh": False,
        },
        metabolic_snapshot=_snapshot(63.0),
        ride_id="manual-profile-sync",
    )

    updated = TwinService().update_from_ride(req)

    assert updated["metabolic_snapshot"]["estimated_vo2max"] == 63.0
