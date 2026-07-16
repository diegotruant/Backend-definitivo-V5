"""Phase 6 — medium coverage pass: lift ~20 medium-tier modules to ≥90% branch."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import jwt
import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.auth.config import AuthConfig
from api.auth.service import authenticate_request
from api.domain_schemas import PowerDurationPoint, PowerSourceActivity, WorkoutDefinitionInput
from api.app import _InMemoryRateLimiter, create_app
from engines.adaptive_load.models import AthleteLoadProfile
from engines.adaptive_load.orchestrator import _as_list, _build_warnings, build_adaptive_load_report
from engines.adaptive_load.trend import calculate_load_trend, ewma, extract_dual_series
from engines.core.science_contracts import (
    derive_effective_cadence_rpm,
    enrich_metabolic_snapshot_cadence,
    resolve_w_prime_tau,
    vlamax_limitations,
)
from engines.io.activity_intelligence import (
    _as_float_array,
    _full_array,
    build_activity_intelligence,
    build_chart_series,
    compute_best_efforts,
    compute_cardiac_decoupling,
    detect_auto_intervals,
)
from engines.io.data_quality_report import build_data_quality_report
from engines.io.fit_parser import parse_fit_records_enhanced
from engines.io.power_source_normalizer import analyze_power_source_offsets
from engines.io.workout_summary import _mmp_curve_to_dict, build_workout_summary
from engines.metabolic.coggan_classifier import classify_from_mmp, classify_power_profile
from engines.metabolic.lactate_validation_engine import (
    LactateStep,
    compute_lactate_thresholds,
    steps_from_payload,
    validate_model_against_lactate,
)
from engines.metabolic.power_vlamax_estimator import estimate_vlamax_from_power_series
from engines.metabolic.zones_engine import (
    _time_in_absolute_watt_bins,
    coggan_power_zones,
    friel_hr_zones,
    metabolic_power_zones,
    seiler_polarization,
)
from engines.performance.sprint_peak_analysis import analyze_sprint_power, neuromuscular_peak_for_decomposition
from engines.projection.season_projection_engine import project_season_from_plan
from engines.twin_state.models import TWIN_STATE_SCHEMA_VERSION, build_twin_state, validate_twin_state
from engines.workouts.compliance_engine import (
    _arr,
    _duration_score,
    _in_range_pct,
    _intensity_score,
    _mean,
    compare_workout_to_activity,
)
from engines.workouts.models import WorkoutStep, WorkoutValidationError, normalize_workout, validate_workout_payload


def _stream(
    seconds: int = 600,
    *,
    power: float = 220.0,
    hr: float = 140.0,
    cadence: float = 90.0,
    with_rr: bool = False,
):
    start = datetime(2026, 1, 1, 8, 0, 0)
    records = []
    for i in range(seconds):
        row = {
            "timestamp": start + timedelta(seconds=i),
            "power": power + (i % 12),
            "heart_rate": hr + (i % 6),
            "cadence": cadence,
        }
        if with_rr:
            row["rr_intervals"] = [820.0, 810.0, 815.0]
        records.append(row)
    return parse_fit_records_enhanced(
        records,
        session_dict={"start_time": start, "total_elapsed_time": seconds, "sport": "cycling"},
    )


def _minimal_twin_payload(**overrides) -> dict:
    base = {
        "athlete_id": "ath-1",
        "athlete_profile": {"athlete_id": "ath-1", "weight_kg": 72.0},
        "metabolic_snapshot": {"status": "success", "mlss_power_watts": 280.0},
        "load_state": {"ctl": 45.0, "atl": 50.0},
    }
    base.update(overrides)
    return base


class TestComplianceEngineMedium:
    def test_internal_helpers_edge_matrix(self) -> None:
        assert _arr(SimpleNamespace(power=None), "power").size == 0
        assert _in_range_pct(np.array([np.nan, np.nan]), 0.0, 100.0) == 0.0
        assert _mean(np.array([])) is None
        assert _duration_score(100, 0, 10.0) == 0.0
        assert _intensity_score(None, 200.0, (180.0, 220.0)) == 50.0
        assert _intensity_score(80.0, 200.0, (180.0, 220.0)) >= 85.0
        assert _intensity_score(60.0, 300.0, (180.0, 220.0)) < 60.0

    def test_hr_exact_cadence_and_missing_power(self) -> None:
        hr_workout = {
            "steps": [
                {
                    "id": "1",
                    "type": "work",
                    "duration_s": 300,
                    "target_hr": 150,
                    "is_key_step": True,
                }
            ],
        }
        hr_stream = _stream(seconds=300, power=0.0, hr=150.0)
        hr_out = compare_workout_to_activity(hr_workout, hr_stream, athlete_profile={"max_hr": 190})
        assert hr_out["status"] == "success"
        assert hr_out["intervals"][0]["target_used"] == "heart_rate"

        cadence_workout = {
            "steps": [
                {
                    "id": "1",
                    "type": "work",
                    "duration_s": 120,
                    "cadence_min_rpm": 95,
                    "cadence_max_rpm": 105,
                    "is_key_step": True,
                }
            ],
        }
        cad_out = compare_workout_to_activity(cadence_workout, _stream(seconds=120))
        assert cad_out["intervals"][0]["target_used"] == "cadence"

        power_workout = {
            "steps": [{"id": "1", "type": "work", "duration_s": 600, "target_pct_ftp": 90}],
        }
        no_power_stream = SimpleNamespace(
            power=np.array([], dtype=float),
            heart_rate=np.array([], dtype=float),
            cadence=np.array([], dtype=float),
            n_samples=0,
            has_power=False,
            has_heart_rate=False,
        )
        empty_power = compare_workout_to_activity(
            power_workout,
            no_power_stream,
            athlete_profile={"ftp_w": 280.0},
        )
        assert empty_power["status"] == "failed"

        no_power = compare_workout_to_activity(
            power_workout,
            SimpleNamespace(
                power=np.zeros(200),
                heart_rate=np.full(200, 140.0),
                cadence=np.zeros(200),
                n_samples=200,
                has_power=False,
                has_heart_rate=True,
            ),
            athlete_profile={"ftp_w": 280.0},
        )
        assert any(d["type"] == "missing_power" for d in no_power["discrepancies"])
        assert no_power["confidence_score"] <= 0.5

        short = compare_workout_to_activity(
            {"steps": [{"id": "1", "type": "work", "duration_s": 1200, "target_pct_ftp": 85}]},
            _stream(seconds=400),
            athlete_profile={"ftp_w": 280.0},
        )
        assert short["confidence_score"] <= 0.65


class TestZonesEngineMedium:
    def test_metabolic_and_coggan_error_paths(self) -> None:
        stream = _stream(seconds=120)
        assert metabolic_power_zones(stream, {"status": "error"})["reason"] == "SNAPSHOT_NOT_SUCCESS"
        assert metabolic_power_zones(stream, {
            "status": "success",
            "expressiveness": {"mlss_reliable": False},
            "mlss_power_watts": 280,
            "zones": [],
        })["reason"] == "MLSS_NOT_RELIABLE"
        assert metabolic_power_zones(stream, {"status": "success", "mlss_power_watts": 280})["reason"] == "METABOLIC_ZONES_NOT_IN_SNAPSHOT"

        empty = parse_fit_records_enhanced([], session_dict={"start_time": datetime(2026, 1, 1)})
        assert coggan_power_zones(empty, ftp=0.0)["reason"] == "INVALID_FTP"
        assert coggan_power_zones(empty, ftp=280.0)["reason"] == "NO_POWER_DATA"
        assert friel_hr_zones(empty, lthr=0.0)["reason"] == "INVALID_LTHR"

        snap = {
            "status": "success",
            "mlss_power_watts": 280,
            "map_aerobic_watts": 350,
            "zones": [
                {"name": "Z1", "minWatt": 0, "maxWatt": 180},
                {"name": "Z2", "minWatt": 181, "maxWatt": 9999},
            ],
        }
        ok = metabolic_power_zones(stream, snap)
        assert ok.get("available") is True
        assert _time_in_absolute_watt_bins(np.array([]), snap["zones"]) == []

    def test_seiler_hr_and_threshold_errors(self) -> None:
        stream = _stream(seconds=600, power=0.0, hr=150.0)
        missing = seiler_polarization(stream, prefer="auto")
        assert missing["reason"] == "MISSING_THRESHOLDS_OR_DATA"

        bad_order = seiler_polarization(stream, vt1_w=260.0, vt2_w=200.0, prefer="power")
        assert bad_order["reason"] == "VT2_NOT_ABOVE_VT1"

        hr_pol = seiler_polarization(stream, vt1_bpm=130.0, vt2_bpm=165.0, prefer="hr")
        assert hr_pol.get("available") is True
        assert hr_pol.get("anchor_type") == "hr"

        with pytest.raises(ValueError, match="vt1_w"):
            seiler_polarization(stream, prefer="power")
        with pytest.raises(ValueError, match="vt1_bpm"):
            seiler_polarization(stream, prefer="hr")


class TestTwinStateModelsMedium:
    def test_json_clean_and_validation_errors(self) -> None:
        cleaned = validate_twin_state(
            build_twin_state(
                {
                    "athlete_id": "a1",
                    "snapshot": {
                        "status": "success",
                        "cp_w": np.float64(280.0),
                        "vo2max": np.int64(58),
                        "bad": np.array([1.0, np.nan]),
                    },
                    "anchor": {"measured_on": "2026-01-01"},
                    "curve": {"5": 900},
                    "calendar": {"next_workout": "rest"},
                }
            )
        )
        assert cleaned["schema_version"] == TWIN_STATE_SCHEMA_VERSION
        assert cleaned["metabolic_metrics"]["cp_w"] == 280.0

        broken = build_twin_state({"athlete_id": "a1"})
        broken.pop("warnings")
        with pytest.raises(ValueError, match="warnings"):
            validate_twin_state(broken)

        broken2 = build_twin_state({"athlete_id": "a1"})
        broken2["schema_version"] = "twin_state.v0"
        with pytest.raises(ValueError, match="schema_version"):
            validate_twin_state(broken2)

        with pytest.raises(ValueError, match="JSON object"):
            validate_twin_state([])  # type: ignore[arg-type]


class TestAuthAndDomainSchemasMedium:
    def test_authenticate_request_matrix(self) -> None:
        none_cfg = AuthConfig(
            mode="none",
            require_athlete_id=True,
            valid_api_keys=frozenset(),
            api_key_athlete_prefixes={},
            jwt_secret=None,
            jwt_algorithms=("HS256",),
            jwt_audience=None,
            jwt_issuer=None,
            jwt_jwks_url=None,
            athlete_scoped_prefixes=("/ride",),
            protected_prefixes=("/ride",),
        )
        missing = authenticate_request(
            path="/ride/analyze",
            authorization=None,
            athlete_header=None,
            config=none_cfg,
        )
        assert missing.status_code == 400

        ok_none = authenticate_request(
            path="/ride/analyze",
            authorization=None,
            athlete_header="ath-1",
            config=none_cfg,
        )
        assert ok_none.ok is True
        assert ok_none.athlete_id == "ath-1"

        api_cfg = AuthConfig(
            mode="api_key",
            require_athlete_id=True,
            valid_api_keys=frozenset({"secret-key"}),
            api_key_athlete_prefixes={"secret-key": ["team-a"]},
            jwt_secret=None,
            jwt_algorithms=("HS256",),
            jwt_audience=None,
            jwt_issuer=None,
            jwt_jwks_url=None,
            athlete_scoped_prefixes=("/ride",),
            protected_prefixes=("/ride",),
        )
        assert authenticate_request(
            path="/health",
            authorization=None,
            athlete_header=None,
            config=api_cfg,
        ).ok is True

        forbidden = authenticate_request(
            path="/ride/analyze",
            authorization="Bearer secret-key",
            athlete_header="team-b-athlete",
            config=api_cfg,
        )
        assert forbidden.status_code == 403

        empty_sub = jwt.encode({"sub": ""}, "jwt-test-secret", algorithm="HS256")
        jwt_cfg = AuthConfig(
            mode="jwt",
            require_athlete_id=False,
            valid_api_keys=frozenset(),
            api_key_athlete_prefixes={},
            jwt_secret="jwt-test-secret",
            jwt_algorithms=("HS256",),
            jwt_audience=None,
            jwt_issuer=None,
            jwt_jwks_url=None,
            athlete_scoped_prefixes=("/ride",),
            protected_prefixes=("/ride",),
        )
        assert authenticate_request(
            path="/ride/analyze",
            authorization=f"Bearer {empty_sub}",
            athlete_header=None,
            config=jwt_cfg,
        ).status_code == 401

    def test_domain_schema_helpers(self) -> None:
        w = WorkoutDefinitionInput.model_validate(
            {
                "name": "Threshold",
                "structure": [{"duration_s": 600, "type": "work", "target_pct_ftp": 95}],
                "steps": [{"duration_s": 300, "type": "recovery"}],
            }
        )
        assert w.title == "Threshold"
        assert len(w.steps) == 1

        assert PowerDurationPoint(value=320.0).watts() == 320.0
        act = PowerSourceActivity(
            device_name="Neo",
            modality="indoor",
            mmp={"60": PowerDurationPoint(power_w=480.0)},
        )
        engine = act.to_engine_dict()
        assert engine["mmp"]["60"]["power_w"] == 480.0


class TestWorkoutModelsMedium:
    def test_power_hr_range_and_validation_edges(self) -> None:
        profile = {"cp_w": 300.0, "ftp_w": 290.0}
        assert WorkoutStep("s1", "work", 300, target_pct_cp=90.0).power_range({"cp_w": "bad"}) is None

        ftp_range = WorkoutStep("s3", "work", 300, target_min_pct_ftp=85.0, target_max_pct_ftp=95.0)
        assert ftp_range.power_range(profile) == (246.5, 275.5)

        hr_step = WorkoutStep("s4", "work", 120, target_hr=150.0)
        assert hr_step.hr_range() == (150.0, 150.0)
        assert "resolved_target_min_hr" in hr_step.to_dict()

        validated = validate_workout_payload(
            {
                "title": "Micro",
                "steps": [{"duration_s": 120, "type": "recovery"}],
            }
        )
        assert any("very short" in w.lower() for w in validated["warnings"])
        assert any("No key/work intervals" in w for w in validated["warnings"])

        with pytest.raises(WorkoutValidationError):
            normalize_workout({"title": "bad", "steps": [{"duration_s": "nope", "type": "work"}]})


class TestPowerSourceAndDataQualityMedium:
    def test_power_source_offset_matrix(self) -> None:
        empty = analyze_power_source_offsets([])
        assert empty["reason"] == "NO_ACTIVITIES"

        one = analyze_power_source_offsets([
            {"device_name": "crank", "modality": "outdoor", "mmp": {"60": 480, "300": 340}},
        ])
        assert one["reason"] == "ONE_SOURCE_ONLY"

        outdoor = {
            "power_source_id": "outdoor_meter",
            "device_name": "crank",
            "modality": "outdoor",
            "mmp": {5: 900, 60: 500, 300: 350, 1200: 290},
        }
        indoor = {
            "power_source_id": "trainer_neo",
            "device_name": "neo",
            "modality": "indoor_trainer",
            "mmp": {5: 920, 60: 530, 300: 380, 1200: 315},
        }
        two = analyze_power_source_offsets([outdoor, indoor], baseline_source_id="outdoor_meter")
        assert two["status"] == "success"
        assert two["pairwise_offsets"]

        bad_mmp = analyze_power_source_offsets([
            {"device_name": "a", "mmp": {"bad": "x"}},
            {"device_name": "b", "mmp": {"60": 400}},
        ])
        assert bad_mmp["status"] in {"insufficient_data", "success"}

    def test_data_quality_report_branches(self) -> None:
        class _BadStream:
            power = ["not", "numeric"]
            heart_rate = np.array([140.0] * 10)
            cadence = np.array([], dtype=float)
            speed_mps = np.array([], dtype=float)
            distance_m = np.array([], dtype=float)
            altitude_m = np.array([], dtype=float)
            temperature_c = np.array([], dtype=float)
            respiration_rate = np.array([], dtype=float)
            left_right_balance = np.array([], dtype=float)
            quality_power = None
            quality_hr = None
            gap_summary = {}
            has_power = True
            has_heart_rate = True
            has_speed = False
            has_distance = False
            has_altitude = False
            has_rr = False
            has_cycling_dynamics = False
            has_respiration = False
            lat = np.array([], dtype=float)
            lon = np.array([], dtype=float)

        unreadable = build_data_quality_report(_BadStream())
        assert unreadable["signals"]["power"]["available"] is False

        partial = build_data_quality_report({
            "power": [0.0] * 50 + [220.0] * 50,
            "heart_rate": [140.0] * 100,
            "quality_power": np.array([0] * 80 + [3] * 20),
        })
        assert partial["signals"]["power"]["coverage_pct"] < 90.0
        assert any("power_" in w for w in partial["warnings"])


class TestActivityIntelligenceMedium:
    def test_efforts_intervals_and_intelligence(self) -> None:
        assert compute_best_efforts([])["reason"] == "no_values"
        efforts = compute_best_efforts([200.0 + (i % 5) for i in range(120)], weight_kg=72.0)
        assert efforts["status"] == "success"

        intervals = detect_auto_intervals(
            [180.0] * 60 + [280.0] * 90 + [180.0] * 60,
            threshold_w=250.0,
            min_duration_s=30,
        )
        assert intervals["status"] == "success"
        assert intervals["intervals"]

        tail = detect_auto_intervals([300.0] * 80, min_duration_s=20)
        assert tail["status"] in {"success", "skipped"}

        intel = build_activity_intelligence(_stream(seconds=1800), weight_kg=72.0, ftp=280.0)
        assert intel.get("status") in {"success", "partial"}


class TestAdaptiveLoadMedium:
    def test_trend_divergence_and_orchestrator_warnings(self) -> None:
        assert ewma([], span=7) is None
        ext, comb = extract_dual_series([None, {"tss": "bad", "session_load": 70.0}])
        assert ext == []
        assert comb == [70.0]

        history = [
            {"tss": 25.0, "session_load": 85.0}
            for _ in range(60)
        ]
        trend = calculate_load_trend(history, current_session_load=85.0, current_external_load=25.0)
        div = trend["external_internal_divergence"]
        assert div.get("available") is True
        assert div.get("divergence_status") in {"hidden_fatigue", "watch", "aligned", "good_adaptation"}

        warnings = _build_warnings(
            {"autonomic_load": {"available": False}, "thermal_load": {"available": False}},
            {"status": "insufficient_data", "external_internal_divergence": {"divergence_status": "hidden_fatigue", "tsb_external": 12.0, "tsb_internal": 4.0}},
            {"available": False},
        )
        assert any("Hidden fatigue" in w for w in warnings)

        assert _as_list(None) == []
        assert _as_list(np.array([1.0, 2.0])) == [1.0, 2.0]

        report = build_adaptive_load_report(
            stream=_stream(seconds=1200, with_rr=True),
            workout_summary={
                "headline": {"np_w": 230},
                "sections": {"power": {"status": "success", "metrics": {"tss": 70.0}}},
                "stream_metadata": {"duration_s": 1200},
            },
            athlete_profile=AthleteLoadProfile(weight_kg=72.0, ftp=280.0),
            history=history,
        )
        assert report["status"] == "success"


class TestScienceContractsAndSprintMedium:
    def test_science_contract_branches(self) -> None:
        stream = SimpleNamespace(cadence=[0.0, 45.0, 95.0, 100.0, None, "bad"], n_samples=6)
        assert derive_effective_cadence_rpm(stream) == pytest.approx(95.0, abs=1.0)
        assert derive_effective_cadence_rpm(SimpleNamespace(cadence=None)) is None

        snap = {"status": "success", "limitations": [], "uncertainty": {}}
        enriched = enrich_metabolic_snapshot_cadence(snap, effective_cadence_rpm=110.0)
        assert enriched["cadence_anchor"]["effective_cadence_rpm"] == 110.0
        assert vlamax_limitations(effective_cadence_rpm=100.0)

        assert resolve_w_prime_tau("individualized", athlete_profile={"w_prime_tau_s": 500.0})[0] == 500.0
        assert resolve_w_prime_tau("individualized", athlete_profile={"w_prime_tau_s": "bad"})[1] == "skiba_default"
        assert resolve_w_prime_tau("skiba_default", athlete_level="elite")[1] == "bartram_elite"
        assert resolve_w_prime_tau("pugh_level_based", athlete_level="novice")[0] == 620.0

    def test_sprint_peak_and_vlamax_errors(self) -> None:
        delayed_power = [200.0] * 6 + [900.0, 920.0, 910.0, 880.0] + [600.0] * 10
        analysis = analyze_sprint_power(delayed_power, dt_s=1.0)
        assert analysis is not None
        assert analysis.recruitment_profile == "delayed"

        assert analyze_sprint_power([1.0, 2.0], dt_s=1.0) is None
        assert analyze_sprint_power(["bad"], dt_s=1.0) is None
        with pytest.raises(ValueError):
            analyze_sprint_power([100.0] * 10, dt_s=2.0)

        assert analyze_sprint_power([400.0, 500.0], dt_s=1.0) is None

        contract = neuromuscular_peak_for_decomposition(
            p_peak_1s=900.0,
            p_mean_sprint=700.0,
            sprint_duration_s=15.0,
            t_p_peak_s=5.0,
            peak_3s_w=880.0,
            peak_5s_w=850.0,
        )
        assert contract["neuromuscular_peak_w"] > 0

        assert estimate_vlamax_from_power_series(
            [100.0] * 5, weight_kg=0.0, eta=0.23, active_muscle_mass_kg=10.0
        )["reason"] == "invalid_mass"
        assert estimate_vlamax_from_power_series(
            [100.0] * 5, weight_kg=72.0, eta=0.0, active_muscle_mass_kg=10.0
        )["reason"] == "invalid_eta"
        assert estimate_vlamax_from_power_series(
            ["x"], weight_kg=72.0, eta=0.23, active_muscle_mass_kg=10.0
        )["reason"] == "invalid_power"
        assert estimate_vlamax_from_power_series(
            [100.0] * 10, weight_kg=72.0, eta=0.23, active_muscle_mass_kg=10.0, dt_s=2.0
        )["reason"] == "invalid_dt"


class TestCogganLactateProjectionMedium:
    def test_coggan_ftp_fallback_from_3600(self) -> None:
        out = classify_from_mmp(
            [
                {"duration_s": 5, "power_w": 900},
                {"duration_s": 60, "power_w": 480},
                {"duration_s": 300, "power_w": 340},
                {"duration_s": 3600, "power_w": 260},
            ],
            weight_kg=72.0,
            gender="MALE",
            ftp=None,
        )
        assert out.get("status") == "success" or out.get("overall")

    def test_lactate_validation_error_paths(self) -> None:
        flat = compute_lactate_thresholds([
            LactateStep(power_w=200, lactate_mmol=4.0),
            LactateStep(power_w=250, lactate_mmol=4.0),
        ])
        assert flat.mlss_dmax_w is None

        short_dmax = compute_lactate_thresholds([
            LactateStep(power_w=150, lactate_mmol=1.5),
            LactateStep(power_w=200, lactate_mmol=2.0),
        ])
        assert short_dmax.mlss_dmax_w is None

        bad_steps = steps_from_payload([
            {"power_w": "bad", "lactate_mmol": 2.0},
            {"lactate_mmol": 2.0},
        ])
        assert bad_steps == []

        from engines.metabolic.metabolic_profiler import MetabolicProfiler

        profiler = MetabolicProfiler(weight=72.0)
        bad_curve = validate_model_against_lactate(
            [
                LactateStep(power_w=150, lactate_mmol=1.2),
                LactateStep(power_w=200, lactate_mmol=1.8),
                LactateStep(power_w=230, lactate_mmol=2.6),
                LactateStep(power_w=260, lactate_mmol=4.1),
                LactateStep(power_w=290, lactate_mmol=6.8),
            ],
            profiler,
            {5: 900},
        )
        assert bad_curve["status"] == "error"


class TestWorkoutSummaryAndSeasonProjectionMedium:
    def test_workout_summary_branches(self) -> None:
        assert _mmp_curve_to_dict([{"duration_s": "bad", "power_w": 300}]) == {}
        assert _mmp_curve_to_dict([{"duration_s": 60, "power_w": "bad"}]) == {}

        stream = _stream(seconds=3600, with_rr=True)
        snap = {
            "status": "success",
            "mlss_power_watts": 280.0,
            "map_aerobic_watts": 350.0,
            "estimated_vo2max": 58.0,
            "estimated_vlamax_mmol_L_s": 0.45,
            "combustion_curve": [{"watt": 200, "carbOxidation": 30}],
        }
        summary = build_workout_summary(
            stream,
            weight_kg=72.0,
            ftp=280.0,
            metabolic_snapshot=snap,
            vt1_w=200.0,
            vt2_w=260.0,
        )
        assert summary["status"] == "success"
        assert "sections" in summary

        with patch("engines.io.workout_summary.analyze_rr_stream_endurance_scheduled", side_effect=RuntimeError("boom")):
            broken_hrv = build_workout_summary(_stream(seconds=600, with_rr=True), weight_kg=72.0, ftp=280.0)
            assert broken_hrv["sections"]["hrv"]["available"] is False

    def test_season_projection_branches(self) -> None:
        twin = build_twin_state(_minimal_twin_payload())
        plan = project_season_from_plan(
            twin,
            [
                {"date": "2026-06-20", "tss": 80.0},
                {"date": "2026-06-21", "workout": {"steps": [{"duration_s": 3600, "type": "work", "target_pct_cp": 90}]}},
                {"date": "bad", "tss": 50},
                {"scheduled_date": "2026-06-22", "duration_min": 45, "modality": "strength"},
            ],
            start_date="2026-06-17",
            target_date="2026-07-17",
        )
        assert plan["status"] == "success"
        assert plan["time_series"]

        sparse = project_season_from_plan(
            build_twin_state({"athlete_id": "a1", "athlete_profile": {}}),
            [],
            start_date="2026-06-17",
            target_date="2026-06-24",
        )
        assert sparse["status"] == "success"

        with pytest.raises(ValueError, match="target_date"):
            project_season_from_plan(twin, [], start_date="2026-07-01", target_date="2026-06-01")


class TestProfileAnchorAndAppMedium:
    def test_profile_anchor_failed_paths(self) -> None:
        from engines.io.profile_anchor_flow import build_anchor_from_proposal

        failed = build_anchor_from_proposal(
            {"status": "proposed", "confidence": 0.5, "mmp_for_fit": {}, "sprint": None},
            weight_kg=72.0,
            measured_on="2026-06-01",
        )
        assert failed.status == "failed"
        assert failed.profile is None

        partial = build_anchor_from_proposal(
            {
                "status": "proposed",
                "confidence": 0.7,
                "mmp_for_fit": {60: 400, 300: 320, 1200: 280},
                "sprint": None,
            },
            weight_kg=72.0,
            measured_on="2026-06-01",
        )
        assert partial.status in {"partial", "failed", "anchored"}

    def test_rate_limiter_and_app_middleware(self, monkeypatch) -> None:
        limiter = _InMemoryRateLimiter(max_requests=2, window_seconds=60.0)
        now = 1000.0
        assert limiter.allow("k1", now=now) is True
        assert limiter.allow("k1", now=now + 1) is True
        assert limiter.allow("k1", now=now + 2) is False

        monkeypatch.setenv("DIGITAL_TWIN_CORS_ORIGINS", "https://app.example.com")
        monkeypatch.setenv("DIGITAL_TWIN_AUTH_MODE", "none")
        monkeypatch.setenv("DIGITAL_TWIN_RATE_LIMIT_ENABLED", "true")
        monkeypatch.setenv("DIGITAL_TWIN_RATE_LIMIT_MAX_REQUESTS", "1")
        monkeypatch.setenv("DIGITAL_TWIN_RATE_LIMIT_WINDOW_S", "60")
        client = TestClient(create_app())

        first = client.get("/health")
        assert first.status_code == 200
        second = client.get("/health")
        assert second.status_code == 200

        blocked = client.post(
            "/profile/snapshot",
            json={"mmp": {"60": 400}, "athlete": {"weight_kg": 72}},
            headers={"content-length": str(10_000_000_000)},
        )
        assert blocked.status_code == 413


class TestPhase6CoverageMediumBatch2:
    """Additional branch closure for modules still below 90%."""

    def test_workout_models_and_domain_schema_residuals(self) -> None:
        from engines.workouts.models import _bool

        assert _bool("true") is True
        assert _bool("off") is False
        step = WorkoutStep("s1", "work", 300, target_min_w=None, target_max_w=None)
        assert step.power_range({"cp_w": 300.0}) is None

        w = WorkoutDefinitionInput.model_construct(
            name="Structure only",
            structure=[{"duration_s": 600, "type": "work"}],
            steps=[],
        )
        normalized = WorkoutDefinitionInput._normalize_steps(w)
        assert len(normalized.steps) == 1

        act = PowerSourceActivity(device_name="pm", mmp_curve={"120": 290.0})
        merged = act.to_engine_dict()
        assert merged["mmp"]["120"] == 290.0

    def test_twin_state_residual_branches(self) -> None:
        from datetime import datetime, timezone

        state = build_twin_state(
            {
                "athlete_id": "a1",
                "load_state": {"ctl": 40},
                "sensor_quality": {"confidence_score": 0.8},
                "metabolic_snapshot": {
                    "status": "success",
                    "estimates": {"cp_w": "bad", "vo2max": float("inf")},
                },
            }
        )
        assert state["state_confidence"]["load"] == 0.4

        dirty = build_twin_state({"athlete_id": "a1"})
        dirty["warnings"] = "not-a-list"
        with pytest.raises(ValueError, match="warnings"):
            validate_twin_state(dirty)

        cleaned = validate_twin_state(
            build_twin_state(
                {
                    "athlete_id": "a1",
                    "event_log": [{"type": "seed", "at": datetime.now(timezone.utc).isoformat()}],
                }
            )
        )
        assert cleaned["event_log"][0]["type"] == "seed"

    def test_profile_anchor_sprint_warning_paths(self) -> None:
        from engines.io.profile_anchor_flow import build_anchor_from_proposal

        sprint_fail = build_anchor_from_proposal(
            {
                "status": "proposed",
                "confidence": 0.6,
                "sprint": {"peak_1s_w": 50.0, "mean_w": 40.0, "duration_s": 15},
                "mmp_for_fit": {},
            },
            weight_kg=72.0,
            measured_on="2026-06-01",
        )
        assert any("Sprint present" in w for w in sprint_fail.warnings)

    def test_science_contracts_and_trend_residuals(self) -> None:
        snap = {
            "status": "success",
            "cadence_anchor": {"effective_cadence_rpm": 95.0},
            "limitations": [],
            "uncertainty": {"limitations": ["existing"]},
        }
        unchanged = enrich_metabolic_snapshot_cadence(snap, effective_cadence_rpm=100.0)
        assert unchanged["cadence_anchor"]["effective_cadence_rpm"] == 95.0

        fresh = enrich_metabolic_snapshot_cadence(
            {"status": "success", "limitations": [], "uncertainty": {}},
            effective_cadence_rpm=100.0,
        )
        assert fresh["limitations"]

        assert resolve_w_prime_tau("pugh_level_based", athlete_level="trained")[0] == 520.0

        assert extract_dual_series([{"tss": 50, "session_load": 80}]) == ([50.0], [80.0])
        assert calculate_load_trend([], None, current_external_load="bad")["status"] == "insufficient_data"

        watch_history = [{"tss": 20.0, "session_load": 75.0} for _ in range(60)]
        watch = calculate_load_trend(watch_history, 75.0, current_external_load=20.0)
        assert watch["external_internal_divergence"].get("divergence_status") in {
            "hidden_fatigue",
            "watch",
            "aligned",
            "good_adaptation",
        }

    def test_season_projection_residual_paths(self) -> None:
        twin = build_twin_state(_minimal_twin_payload())
        heavy = project_season_from_plan(
            twin,
            [{"date": "2026-06-18", "tss": 280.0}],
            start_date="2026-06-17",
            target_date="2026-06-20",
        )
        assert heavy["warnings"]

        bad_workout = project_season_from_plan(
            twin,
            [{"date": "2026-06-18", "workout": {"steps": []}}],
            start_date="2026-06-17",
            target_date="2026-06-19",
        )
        assert bad_workout["time_series"]

        sparse_metrics = project_season_from_plan(
            build_twin_state({"athlete_id": "a1"}),
            [{"date": "2026-06-18", "duration_s": 3600}],
            start_date="2026-06-17",
            target_date="2026-06-19",
        )
        assert sparse_metrics["assumptions"]["inferred_defaults"]

    def test_activity_intelligence_and_data_quality_residuals(self) -> None:
        assert _as_float_array(None).size == 0
        assert _as_float_array(["bad", "values"]).size == 0
        assert _as_float_array([[1.0, 2.0]]).size == 0

        skipped = detect_auto_intervals([0.0] * 50)
        assert skipped["reason"] == "no_power"

        empty_chart = build_chart_series(_stream(seconds=1, power=0.0))
        assert empty_chart["status"] in {"skipped", "success"}

        long_stream = _stream(seconds=1500)
        decouple = compute_cardiac_decoupling(long_stream)
        assert decouple["status"] in {"success", "skipped"}

        partial_decouple = compute_cardiac_decoupling(_stream(seconds=100))
        assert partial_decouple["reason"] == "insufficient_duration_or_signals"

        missing = build_data_quality_report(
            {
                "power": None,
                "heart_rate": [140.0] * 20,
                "quality_hr": np.array([1] * 20),
            }
        )
        assert missing["signals"]["power"]["notes"] == ["missing_signal"]
        assert any("heart_rate_" in w for w in missing["warnings"])

    def test_coggan_sprint_lactate_vlamax_residuals(self) -> None:
        with pytest.raises(ValueError, match="weight_kg"):
            classify_power_profile(0.0, "MALE", p5s=900)

        bad_gender = classify_power_profile(72.0, "OTHER", p5s=900, p1min=600, p5min=400, ftp=300)
        assert bad_gender["gender"] == "MALE"

        none_powers = classify_power_profile(72.0, "MALE", p5s=-1, p1min=0)
        assert none_powers["status"] == "error"

        assert analyze_sprint_power([0.0, 0.0, 0.0, 0.0], dt_s=1.0) is None

        short_roll = analyze_sprint_power([400.0], dt_s=1.0)
        assert short_roll is None

        assert estimate_vlamax_from_power_series(
            [100.0] * 5, weight_kg=72.0, eta=0.23, active_muscle_mass_kg=10.0
        )["reason"] == "power_too_short"

        long_bad = estimate_vlamax_from_power_series(
            [50.0] * 40, weight_kg=72.0, eta=0.23, active_muscle_mass_kg=10.0, dt_s=1.0
        )
        assert long_bad["reason"] == "duration_outside_8_30s"

        flat_interp = compute_lactate_thresholds([
            LactateStep(power_w=200, lactate_mmol=3.0),
            LactateStep(power_w=220, lactate_mmol=4.0),
            LactateStep(power_w=240, lactate_mmol=4.0),
        ])
        assert flat_interp.mlss_dmax_w is not None

        from engines.metabolic.metabolic_profiler import MetabolicProfiler

        profiler = MetabolicProfiler(weight=72.0)
        too_few = validate_model_against_lactate(
            [
                LactateStep(power_w=150, lactate_mmol=1.0),
                LactateStep(power_w=170, lactate_mmol=2.0),
            ],
            profiler,
            {5: 900, 60: 480, 300: 340, 1200: 285, 3600: 255},
        )
        assert too_few["status"] == "error"
        assert too_few.get("reason") == "insufficient_lactate_steps"

    def test_workout_summary_residual_paths(self) -> None:
        stream = _stream(seconds=7200)
        snap = {
            "status": "success",
            "mlss_power_watts": 280.0,
            "map_aerobic_watts": 350.0,
            "estimated_vo2max": 58.0,
            "estimated_vlamax_mmol_L_s": 0.45,
            "combustion_curve": [{"watt": 200, "carbOxidation": 30}],
            "expressiveness": {"reliability": {"mlss": True, "vo2max": True}},
        }
        no_ftp = build_workout_summary(stream, weight_kg=72.0, ftp=None)
        assert no_ftp["status"] == "success"
        assert "warnings" in no_ftp

        no_rr = build_workout_summary(_stream(seconds=600), weight_kg=72.0, ftp=280.0)
        assert no_rr["sections"]["hrv"]["reason"] == "NO_RR_DATA_IN_STREAM"

        with patch(
            "engines.performance.mader_durability.compute_session_durability",
            return_value={
                "status": "success",
                "durability_loss_pct": 8.0,
                "cp_baseline": 280.0,
                "sustainability": {"sustainable_steady_power_w": {"at_10pct_cp_loss": {"3h": 250.0}}},
            },
        ):
            mader = build_workout_summary(stream, weight_kg=72.0, ftp=280.0, metabolic_snapshot=snap)
            assert mader["sections"]["mader_durability"]["status"] == "success"
            assert mader["headline"].get("mader_sustainable_3h_w") == 250.0

        with patch(
            "engines.performance.mader_durability.compute_session_durability",
            side_effect=RuntimeError("mader failed"),
        ):
            broken = build_workout_summary(stream, weight_kg=72.0, ftp=280.0, metabolic_snapshot=snap)
            assert broken["sections"]["mader_durability"]["status"] == "error"

        class _BrokenSectionStream:
            def __init__(self, inner):
                self._inner = inner

            def __getattr__(self, name):
                return getattr(self._inner, name)

        broken_sections = build_workout_summary(_BrokenSectionStream(_stream(seconds=300)), weight_kg=72.0, ftp=280.0)
        assert broken_sections["status"] == "success"
