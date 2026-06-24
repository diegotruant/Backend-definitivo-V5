"""Phase 4 coverage depth — targeted tests for low-coverage public APIs."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List

import numpy as np
import pytest

from api.domain_schemas import TwinStateDocument
from api.engine_schemas import (
    AdaptiveLoadRequest,
    DurabilityIndexRequest,
    EffortsAnalyzeRequest,
    SessionClassifyRequest,
    WPrimeBalanceRequest,
    ZonesAnalyzeRequest,
)
from api.errors import ServiceError
from api.schemas import AthleteParams, SeasonProjectionRequest, TeamCalibrationApplyRequest, TwinStateBuildRequest
from api.services.profile_extended_service import ProfileExtendedService
from api.services.ride_analytics_service import RideAnalyticsService
from api.services.team_service import TeamService
from api.services.twin_service import TwinService
from engines.core import security
from engines.core.data_quality_engine import assess_data_quality, clean_workout_data, detect_pauses
from engines.io.fit_parser import parse_fit_records_enhanced
from engines.metabolic.team_learning_engine import TeamCalibrationModel, ValidationEvent
from engines.performance.interval_detector import classify_session, protocol_completeness
from engines.performance.mmp_quality import analyze_mmp_quality, clean_mmp
from engines.recovery.hrv_engine import analyze_rr_stream
from tests._fixtures import twin_build_payload, workout_pct_cp


def _stream(
    *,
    seconds: int = 3600,
    power: float = 250.0,
    with_rr: bool = False,
    device_name: str | None = None,
) -> Any:
    start = datetime(2026, 1, 1, 8, 0, 0)
    records: List[Dict[str, Any]] = []
    for i in range(seconds):
        row: Dict[str, Any] = {
            "timestamp": start + timedelta(seconds=i),
            "power": power,
            "heart_rate": 140 + (i % 20),
            "cadence": 90,
        }
        if with_rr:
            row["rr_intervals"] = [820.0, 810.0, 805.0]
        records.append(row)
    session: Dict[str, Any] = {
        "sport": "cycling",
        "start_time": start,
        "total_elapsed_time": seconds,
    }
    if device_name:
        session["device_name"] = device_name
    return parse_fit_records_enhanced(records, session_dict=session)


def _twin_doc() -> TwinStateDocument:
    state = TwinService().build(TwinStateBuildRequest(payload=twin_build_payload()))
    return TwinStateDocument.model_validate(state)


class TestDataQualityEngine:
    def test_assess_good_streams(self) -> None:
        power = [220 + (i % 10) for i in range(600)]
        hr = [140 + (i % 5) for i in range(600)]
        cadence = [90 + (i % 3) for i in range(600)]
        report = assess_data_quality(power, hr, cadence)
        assert report.overall_score >= 0.6
        assert report.usable_for_analysis

    def test_assess_detects_low_quality_power(self) -> None:
        power = [0.0] * 200 + [50.0] * 100
        report = assess_data_quality(power)
        assert report.power_quality < 1.0
        assert report.overall_score < 1.0

    def test_clean_workout_data_removes_pauses(self) -> None:
        power = [0.0] * 30 + [250.0] * 120 + [0.0] * 30 + [250.0] * 120
        out = clean_workout_data(power, remove_pauses_flag=True)
        assert out["power_cleaned"]
        assert out["quality_report"].overall_score >= 0
        pauses = detect_pauses(power)
        assert pauses


class TestIntervalDetector:
    def test_classify_by_filename_ramp_test(self) -> None:
        powers = [150 + i * 2 for i in range(600)]
        result = classify_session(powers, filename="athlete_ramp_test.fit", ftp=280)
        assert result.category == "TEST"
        assert result.subtype == "ramp_test"
        assert result.source == "filename"

    def test_classify_with_explicit_hint(self) -> None:
        result = classify_session([200] * 300, hint=("ENDURANCE", "steady"), ftp=250)
        assert result.category == "ENDURANCE"
        assert result.confidence == 1.0

    def test_protocol_completeness_reports_gaps(self) -> None:
        report = protocol_completeness(available_durations_s=[60, 300, 1200])
        body = report.to_dict()
        assert "completeness_pct" in body
        assert body["completeness_pct"] >= 0


class TestMmpQuality:
    def test_detects_identical_plateau(self) -> None:
        mmp = {300: 320.0, 600: 320.0, 1200: 310.0, 1800: 305.0}
        report = analyze_mmp_quality(mmp)
        assert report.total_anchors == 4
        assert any(i.category == "identical_plateau" for i in report.issues)

    def test_clean_mmp_drops_redundant_anchors(self) -> None:
        mmp = {300: 320.0, 600: 320.0, 1200: 310.0}
        cleaned, audit = clean_mmp(mmp)
        assert len(cleaned) < len(mmp)
        assert audit["dropped"]


class TestHrvEngine:
    def test_analyze_rr_stream_returns_windows(self) -> None:
        rr_samples = [
            {"elapsed": float(i * 5), "rr": [800.0 + (i % 7)] * 20}
            for i in range(80)
        ]
        timeline = analyze_rr_stream(rr_samples, window_seconds=60, step_seconds=10.0)
        assert isinstance(timeline, list)

    def test_analyze_rr_stream_empty_input(self) -> None:
        assert analyze_rr_stream([]) == []


class TestTeamServiceDepth:
    def test_apply_calibration_snapshot_path(self) -> None:
        model = TeamCalibrationModel.fit(
            [
                ValidationEvent(
                    athlete_id="r1",
                    team_id="wt",
                    parameter="mlss",
                    predicted_value=280,
                    measured_value=270,
                )
                for _ in range(5)
            ],
            team_id="wt",
        )
        svc = TeamService()
        out = svc.apply_calibration(
            TeamCalibrationApplyRequest(
                calibration_model=model.to_dict(),
                snapshot={"status": "success", "mlss_power_watts": 285},
                athlete_id="r1",
            )
        )
        assert out["mlss_power_watts"] <= 285

    def test_apply_calibration_requires_parameter_or_snapshot(self) -> None:
        svc = TeamService()
        with pytest.raises(ServiceError) as exc:
            svc.apply_calibration(
                TeamCalibrationApplyRequest(calibration_model={"team_id": "wt", "events": [], "corrections": {}})
            )
        assert exc.value.code == "CALIBRATION_APPLY_INPUT"

    def test_update_calibration_invalid_event_raises(self) -> None:
        from api.schemas import TeamCalibrationUpdateRequest

        svc = TeamService()
        with pytest.raises(ServiceError) as exc:
            svc.update_calibration(
                TeamCalibrationUpdateRequest(team_id="wt", events=[{"parameter": "mlss", "predicted_value": -1}])
            )
        assert exc.value.code == "CALIBRATION_UPDATE"


class TestTwinServiceDepth:
    def test_project_season_rejects_deep_payload(self) -> None:
        deep: object = {"v": 1}
        for _ in range(security.MAX_JSON_DEPTH + 5):
            deep = {"nested": deep}
        twin = _twin_doc()
        twin_dict = twin.model_dump()
        twin_dict["athlete_profile"] = deep
        req = SeasonProjectionRequest(
            twin_state=TwinStateDocument.model_validate(twin_dict),
            calendar_plan=[],
            start_date="2026-06-01",
            target_date="2026-06-03",
        )
        with pytest.raises(ServiceError) as exc:
            TwinService().project_season(req)
        assert exc.value.code == "PAYLOAD_TOO_DEEP"

    def test_project_season_success_with_empty_calendar(self) -> None:
        req = SeasonProjectionRequest(
            twin_state=_twin_doc(),
            calendar_plan=[],
            start_date="2026-06-01",
            target_date="2026-06-05",
        )
        out = TwinService().project_season(req)
        assert out["status"] == "success"
        assert len(out["time_series"]) == 5


class TestRideAnalyticsServiceDepth:
    def setup_method(self) -> None:
        self.svc = RideAnalyticsService()
        self.stream = _stream(seconds=7200, power=255.0)
        self.athlete = AthleteParams(weight_kg=72.0, ftp=280.0)

    def test_zones_analyze(self) -> None:
        out = self.svc.zones(
            self.stream,
            ZonesAnalyzeRequest(athlete=self.athlete, ftp=280.0),
        )
        assert "zones" in out or out.get("status") in {"success", "partial"}

    def test_classify_session_ride(self) -> None:
        stream = _stream(seconds=1800, device_name="ftp_20min_test.fit")
        out = self.svc.classify_session_ride(
            stream,
            SessionClassifyRequest(athlete=self.athlete, ftp=280.0),
        )
        assert out.get("category") == "TEST"

    def test_protocol_completeness_service(self) -> None:
        out = self.svc.protocol_completeness(self.stream)
        assert "completeness_pct" in out

    def test_resilience_and_metabolic_flexibility(self) -> None:
        assert self.svc.resilience(mader_durability={"status": "success", "durability_loss_pct": 5.0})
        partial = self.svc.metabolic_flexibility({"estimated_vo2max": 55})
        assert partial["status"] == "partial"
        ok = self.svc.metabolic_flexibility({"fatmax_power_watts": 200, "mlss_power_watts": 280})
        assert ok.get("status") == "success"

    def test_hrv_and_cardiac_edge_cases(self) -> None:
        no_rr = self.svc.hrv_analyze(self.stream)
        assert no_rr["status"] == "error"
        cardiac = self.svc.cardiac(self.stream, athlete=self.athlete, metabolic_snapshot=None)
        assert cardiac.get("status") in {"success", "partial", "error"}

    def test_w_prime_balance_and_durability(self) -> None:
        power = [300] * 600 + [200] * 300
        bal = self.svc.w_prime_balance(
            WPrimeBalanceRequest(power=power, cp=270, w_prime=20000, dt_s=1.0)
        )
        assert "balance" in bal
        di = self.svc.durability_index(DurabilityIndexRequest(power=power))
        assert di["status"] in {"success", "insufficient_duration"}

    def test_efforts_analyze(self) -> None:
        out = self.svc.efforts(
            self.stream,
            EffortsAnalyzeRequest(athlete=self.athlete, ftp=280.0, cp_w=270.0),
        )
        assert out.get("status") in {"success", "partial", "warning"}


class TestProfileExtendedServiceDepth:
    def test_mmp_quality_endpoint_logic(self) -> None:
        svc = ProfileExtendedService()
        from api.engine_schemas import MmpQualityRequest

        out = svc.mmp_quality(MmpQualityRequest(mmp={"300": 320, "600": 320, "1200": 300}))
        assert "quality_score" in out
        assert "issues" in out

    def test_ctl_atl_tsb_history(self) -> None:
        svc = ProfileExtendedService()
        out = svc.ctl_atl_tsb([{"date": "2026-01-01", "tss": 50}] * 14)
        assert "ctl" in out
        assert "tsb" in out
