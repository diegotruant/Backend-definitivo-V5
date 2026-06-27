from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from api.engine_schemas import (
    BayesianSnapshotRequest,
    CrossValidateRequest,
    DetrainingApplyRequest,
    FatmaxCompareRequest,
    FatmaxLabRequest,
    FatmaxReportRequest,
    GlycolyticProfileRequest,
    KalmanTrajectoryRequest,
    MetabolicCurrentRequest,
    MmpAthleteRequest,
    MmpQualityRequest,
    SegmentedSnapshotRequest,
    VlamaxPowerSeriesRequest,
    VlamaxSprintRequest,
)
from api.schemas import SnapshotRequest
from api.services.engine_context import athlete_context_from_params, mmp_dict, profiler_from_athlete
from api.services.profile_service import ProfileService
from engines.core.science_contracts import resolve_w_prime_tau
from engines.metabolic.bayesian_profiler import bayesian_metabolic_snapshot
from engines.metabolic.cross_validation_engine import cross_validate_metabolic_profile
from engines.metabolic.detraining_engine import apply_detraining_model, calculate_ctl_atl_tsb
from engines.metabolic.fatmax_engine import (
    GasExchangePoint,
    build_lab_fatmax_report,
    build_model_fatmax_report,
    compare_fatmax_reports,
)
from engines.metabolic.glycolytic_validation_engine import build_glycolytic_profile
from engines.metabolic.metabolic_current import get_current_metabolic_status
from engines.metabolic.metabolic_kalman import DailyInput, process_workout_history
from engines.metabolic.metabolic_profiler_phenotype import enhance_metabolic_snapshot_with_phenotype
from engines.metabolic.power_vlamax_estimator import estimate_vlamax_from_power_series
from engines.performance.mmp_quality import analyze_mmp_quality, clean_mmp


def _with_sprint_vlamax_confidence(result: Dict[str, Any]) -> Dict[str, Any]:
    """Propagate tau_alactic sensitivity into the endpoint-level confidence score."""
    if result.get("status") != "success":
        result.setdefault("confidence_score", 0.0)
        return result

    vlamax = result.get("vlamax_mmol_l_s")
    vlamax_range = result.get("vlamax_range") or []
    if vlamax is None or not isinstance(vlamax_range, list) or len(vlamax_range) < 2:
        result.setdefault("confidence_score", 0.55)
        return result
    try:
        point = float(vlamax)
        lo = float(vlamax_range[0])
        hi = float(vlamax_range[1])
    except (TypeError, ValueError, IndexError):
        result.setdefault("confidence_score", 0.55)
        return result

    range_width = max(0.0, hi - lo)
    sensitivity_ratio = range_width / max(point, 0.05)
    quality_flags = list(result.get("quality_flags") or [])
    if sensitivity_ratio >= 0.75:
        quality_flags.append("tau_alactic_sensitivity_high")
    elif sensitivity_ratio >= 0.45:
        quality_flags.append("tau_alactic_sensitivity_moderate")

    confidence = 0.82
    confidence -= min(0.32, sensitivity_ratio * 0.35)
    confidence -= min(0.12, 0.03 * len(set(quality_flags)))
    confidence = max(0.35, min(0.90, confidence))

    result["confidence_score"] = round(confidence, 3)
    result["tau_alactic_sensitivity"] = {
        "vlamax_range_width": round(range_width, 3),
        "relative_to_point_estimate": round(sensitivity_ratio, 3),
        "confidence_penalty_applied": True,
    }
    result["quality_flags"] = sorted(set(quality_flags))
    return result


class ProfileExtendedService:
    def __init__(self) -> None:
        self._base = ProfileService()

    def build_snapshot(self, req: SnapshotRequest) -> Dict[str, Any]:
        return self._base.build_snapshot(req)

    def segmented_snapshot(self, req: SegmentedSnapshotRequest) -> Dict[str, Any]:
        profiler = profiler_from_athlete(req.athlete)
        return profiler.generate_metabolic_snapshot_segmented(
            mmp_dict(req.mmp),
            aerobic_min_duration_s=req.aerobic_min_duration_s,
            expected_eta=req.expected_eta,
            measured_lacap=req.measured_lacap,
            effective_cadence_rpm=req.effective_cadence_rpm,
            clean_mmp_first=req.clean_mmp_first,
        )

    def auto_snapshot(self, req: MmpAthleteRequest) -> Dict[str, Any]:
        profiler = profiler_from_athlete(req.athlete)
        return profiler.generate_metabolic_snapshot_auto(
            mmp_dict(req.mmp),
            expected_eta=req.expected_eta,
            measured_lacap=req.measured_lacap,
            effective_cadence_rpm=req.effective_cadence_rpm,
            clean_mmp_first=req.clean_mmp_first,
        )

    def bayesian_snapshot(self, req: BayesianSnapshotRequest) -> Dict[str, Any]:
        profiler = profiler_from_athlete(req.athlete)
        result = bayesian_metabolic_snapshot(
            profiler,
            mmp_dict(req.mmp),
            expected_eta=req.expected_eta,
            measured_lacap=req.measured_lacap,
            n_samples=req.n_samples,
            n_warmup=req.n_warmup,
            seed=req.seed,
        )
        return result.to_dict()

    def vlamax_from_sprint(self, req: VlamaxSprintRequest) -> Dict[str, Any]:
        profiler = profiler_from_athlete(req.athlete)
        result = profiler.vlamax_from_sprint(
            req.p_peak_1s,
            req.p_mean_sprint,
            sprint_duration_s=req.sprint_duration_s,
            vo2max_power_w=req.vo2max_power_w,
            t_p_peak_s=req.t_p_peak_s,
            peak_3s_w=req.peak_3s_w,
            peak_5s_w=req.peak_5s_w,
            neuromuscular_peak_w=req.neuromuscular_peak_w,
        )
        return _with_sprint_vlamax_confidence(result)

    def vlamax_from_power_series(self, req: VlamaxPowerSeriesRequest) -> Dict[str, Any]:
        profiler = profiler_from_athlete(req.athlete)
        return estimate_vlamax_from_power_series(
            req.power,
            dt_s=req.dt_s,
            weight_kg=req.athlete.weight_kg,
            eta=profiler.context.expected_eta(),
            active_muscle_mass_kg=profiler.active_muscle_mass,
            vo2max_power_w=req.vo2max_power_w,
            cp_w=req.cp_w,
            lactate_pre_mmol_l=req.lactate_pre_mmol_l,
            lactate_peak_mmol_l=req.lactate_peak_mmol_l,
        )

    def kalman_trajectory(self, req: KalmanTrajectoryRequest) -> Dict[str, Any]:
        profiler = profiler_from_athlete(req.athlete)
        daily: List[DailyInput] = []
        for row in req.daily_inputs:
            anchors = None
            if row.test_anchors:
                anchors = [(int(a[0]), float(a[1])) for a in row.test_anchors if len(a) >= 2]
            daily.append(
                DailyInput(
                    date=date.fromisoformat(row.date.split("T")[0]),
                    vo2max_stimulus_min=row.vo2max_stimulus_min,
                    threshold_stimulus_min=row.threshold_stimulus_min,
                    anaerobic_stimulus_min=row.anaerobic_stimulus_min,
                    neuromuscular_stimulus_min=row.neuromuscular_stimulus_min,
                    test_anchors=anchors,
                )
            )
        traj = process_workout_history(
            daily,
            initial_vo2=req.initial_vo2,
            initial_vla=req.initial_vla,
            weight=req.athlete.weight_kg,
            initial_vo2_std=req.initial_vo2_std,
            initial_vla_std=req.initial_vla_std,
            athlete_id=req.athlete_id,
            profiler=profiler,
        )
        return traj.to_dict()

    def metabolic_current(self, req: MetabolicCurrentRequest) -> Dict[str, Any]:
        ctx = athlete_context_from_params(req.athlete)
        return get_current_metabolic_status(
            historical_mmp=mmp_dict(req.historical_mmp),
            workout_history=req.workout_history,
            athlete_weight_kg=req.athlete.weight_kg,
            athlete_context={
                "gender": ctx.effective_gender(),
                "training_years": ctx.effective_training_years(),
                "discipline": ctx.effective_discipline(),
            },
            today=req.as_of,
        )

    def apply_detraining(self, req: DetrainingApplyRequest) -> Dict[str, Any]:
        ref = req.as_of or date.today().isoformat()
        ref_date = datetime.fromisoformat(ref.split("T")[0]).date()
        return apply_detraining_model(
            baseline_snapshot=req.baseline_snapshot,
            workout_history=req.workout_history,
            today=ref_date,
        )

    def ctl_atl_tsb(self, tss_history: List[Dict[str, Any]]) -> Dict[str, Any]:
        normalized: List[Dict[str, Any]] = []
        for row in tss_history:
            entry = dict(row)
            raw_date = entry.get("date")
            if isinstance(raw_date, str):
                entry["date"] = date.fromisoformat(raw_date.split("T")[0])
            normalized.append(entry)
        return calculate_ctl_atl_tsb(normalized, date.today())

    def cross_validate(self, req: CrossValidateRequest) -> Dict[str, Any]:
        profiler = profiler_from_athlete(req.athlete)
        snap = profiler.generate_metabolic_snapshot(
            mmp_dict(req.mmp),
            expected_eta=req.expected_eta,
            measured_lacap=req.measured_lacap,
            effective_cadence_rpm=req.effective_cadence_rpm,
            clean_mmp_first=req.clean_mmp_first,
        )
        if snap.get("status") != "success":
            return {"status": "error", "snapshot": snap}
        vo2max = snap.get("estimated_vo2max")
        vlamax = snap.get("estimated_vlamax_mmol_L_s")
        if vo2max is None or vlamax is None:
            return {"status": "partial", "snapshot": snap, "reason": "MISSING_FITTED_PARAMETERS"}
        cv = cross_validate_metabolic_profile(
            profiler,
            mmp_dict(req.mmp),
            float(vo2max),
            float(vlamax),
        )
        return {"status": "success", "snapshot": snap, "cross_validation": cv.to_dict()}

    def mmp_quality(self, req: MmpQualityRequest) -> Dict[str, Any]:
        mmp = mmp_dict(req.mmp)
        if req.clean:
            cleaned, audit = clean_mmp(mmp)
            return {"status": "success", "mmp": cleaned, "audit": audit}
        report = analyze_mmp_quality(mmp)
        return report.to_dict() if hasattr(report, "to_dict") else dict(report)

    def phenotype_enhance(self, req: GlycolyticProfileRequest) -> Dict[str, Any]:
        profiler = profiler_from_athlete(req.athlete)
        snap = profiler.generate_metabolic_snapshot(
            mmp_dict(req.mmp),
            expected_eta=req.expected_eta,
            measured_lacap=req.measured_lacap,
            effective_cadence_rpm=req.effective_cadence_rpm,
        )
        return enhance_metabolic_snapshot_with_phenotype(snap)

    def glycolytic_profile(self, req: GlycolyticProfileRequest) -> Dict[str, Any]:
        profiler = profiler_from_athlete(req.athlete)
        snap = profiler.generate_metabolic_snapshot(
            mmp_dict(req.mmp),
            expected_eta=req.expected_eta,
            measured_lacap=req.measured_lacap,
            effective_cadence_rpm=req.effective_cadence_rpm,
        )
        end_max, all_max = profiler.context.phenotype_thresholds()
        return build_glycolytic_profile(
            snap,
            profiler=profiler,
            mmp=mmp_dict(req.mmp),
            endurance_max=end_max,
            allrounder_max=all_max,
            sprint_power=req.sprint_power,
        )

    def fatmax_report(self, req: FatmaxReportRequest) -> Dict[str, Any]:
        snapshot = req.metabolic_snapshot
        if snapshot is None:
            profiler = profiler_from_athlete(req.athlete)
            snapshot = profiler.generate_metabolic_snapshot(
                mmp_dict(req.mmp),
                expected_eta=req.expected_eta,
                measured_lacap=req.measured_lacap,
                effective_cadence_rpm=req.effective_cadence_rpm,
                clean_mmp_first=req.clean_mmp_first,
            )
            if snapshot.get("status") != "success":
                return {
                    "status": "insufficient_data",
                    "schema_version": "fatmax_report.v1",
                    "measurement_tier": "INSUFFICIENT_DATA",
                    "reason": "metabolic_snapshot_generation_failed",
                    "source_snapshot": snapshot,
                    "confidence_score": 0.0,
                    "limitations": ["Metabolic snapshot could not be built from supplied MMP."],
                }
        ctx = athlete_context_from_params(req.athlete)
        return build_model_fatmax_report(
            snapshot,
            athlete_weight_kg=req.athlete.weight_kg,
            gender=ctx.effective_gender(),
            training_years=ctx.effective_training_years(),
            discipline=ctx.effective_discipline(),
            recent_training_status=req.recent_training_status,
            environment_context=req.environment_context,
            nutrition_context=req.nutrition_context,
            previous_report=req.previous_report,
            threshold_fraction=req.threshold_fraction,
        )

    def fatmax_lab(self, req: FatmaxLabRequest) -> Dict[str, Any]:
        points = [
            GasExchangePoint(
                power_w=row.power_w,
                vo2_l_min=row.vo2_l_min,
                vco2_l_min=row.vco2_l_min,
                rer=row.rer,
                heart_rate_bpm=row.heart_rate_bpm,
            )
            for row in req.points
        ]
        return build_lab_fatmax_report(
            points,
            athlete_weight_kg=req.athlete.weight_kg if req.athlete else None,
            mlss_power_w=req.mlss_power_w,
            map_power_w=req.map_power_w,
            threshold_fraction=req.threshold_fraction,
        )

    def fatmax_compare(self, req: FatmaxCompareRequest) -> Dict[str, Any]:
        return {
            "status": "success",
            "schema_version": "fatmax_shift.v1",
            "shift": compare_fatmax_reports(req.previous_report, req.current_report).to_dict(),
        }

    def w_prime_tau(
        self,
        tau_model: str,
        athlete_profile: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        profile = athlete_profile or {}
        tau_s, model_used = resolve_w_prime_tau(
            tau_model,
            athlete_profile=profile,
            athlete_level=profile.get("level") or profile.get("athlete_level"),
        )
        return {
            "tau_s": round(tau_s, 1),
            "tau_model": model_used,
        }
