from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from api.engine_schemas import (
    AdaptiveLoadRequest,
    DurabilityIndexRequest,
    EffortsAnalyzeRequest,
    SessionClassifyRequest,
    WPrimeBalanceRequest,
    ZonesAnalyzeRequest,
)
from api.schemas import AthleteParams
from api.services.engine_context import athlete_context_from_params, power_list, profiler_from_athlete
from engines.adaptive_load.models import AthleteLoadProfile, DailyStatus
from engines.adaptive_load.orchestrator import build_adaptive_load_report
from engines.io.activity_statistics import compute_activity_statistics
from engines.io.session_router import decide_route, route_and_run
from engines.io.workout_summary import build_workout_summary
from engines.metabolic.metabolic_flexibility_engine import calculate_metabolic_flexibility_index
from engines.metabolic.zones_engine import ZonesEngine
from engines.performance.durability_engine import (
    calculate_durability_index,
    calculate_np_drift,
    calculate_tte_sustainability,
    generate_durability_prescription,
    generate_hourly_decay_curve,
)
from engines.performance.efforts_analyzer import analyze_efforts
from engines.performance.interval_detector import classify_session, protocol_completeness
from engines.performance.physiological_resilience import build_physiological_resilience
from engines.performance.power_engine import PowerEngine, estimate_ftp_from_mmp, fit_critical_power
from engines.performance.w_prime_balance_engine import analyze_w_prime_usage, calculate_w_prime_balance
from engines.recovery.cardiac_engine import ActivitySample, CardiacResponseAnalyzer
from engines.core.tiers import tier_for
from engines.recovery.hrv_engine import analyze_rr_stream
from engines.recovery.pedaling_balance import analyze_pedaling_balance
from engines.recovery.thermal_engine import analyze_heat_acclimation, analyze_thermal_session
from engines.routes.segment_engine import compare_segments, detect_climb_segments


class RideAnalyticsService:
    def zones(self, stream: Any, req: ZonesAnalyzeRequest) -> Dict[str, Any]:
        engine = ZonesEngine(ftp=req.ftp, lthr=req.lthr)
        return engine.analyze(
            stream,
            metabolic_snapshot=req.metabolic_snapshot,
            vt1_w=req.vt1_w,
            vt2_w=req.vt2_w,
            vt1_bpm=req.vt1_bpm,
            vt2_bpm=req.vt2_bpm,
        )

    def statistics(
        self,
        stream: Any,
        *,
        weight_kg: float,
        ftp: Optional[float],
        lthr: Optional[float],
        cp: Optional[float],
    ) -> Dict[str, Any]:
        return compute_activity_statistics(stream, weight_kg=weight_kg, ftp=ftp, lthr=lthr, cp=cp)

    def power_analyze(self, stream: Any, *, weight_kg: float, ftp: Optional[float]) -> Dict[str, Any]:
        ftp_used = ftp
        engine_tmp = PowerEngine(ftp=200.0, weight_kg=weight_kg)
        tmp = engine_tmp.analyze(stream)
        if ftp_used is None:
            est = estimate_ftp_from_mmp(tmp.get("mmp_curve") or [])
            ftp_used = est.get("ftp_w")
        if ftp_used is None:
            np_w = tmp.get("normalized_power") or tmp.get("np") or tmp.get("avg_power")
            if np_w:
                ftp_used = float(np_w) * 0.95
        if ftp_used is None:
            return {"status": "error", "reason": "FTP_NOT_AVAILABLE"}
        return PowerEngine(ftp=ftp_used, weight_kg=weight_kg).analyze(stream)

    def critical_power_fit(self, mmp_curve: List[Dict[str, Any]]) -> Dict[str, Any]:
        result = fit_critical_power(mmp_curve)
        return result if result else {"status": "partial", "reason": "FIT_FAILED"}

    def w_prime_balance(self, req: WPrimeBalanceRequest) -> Dict[str, Any]:
        balance = calculate_w_prime_balance(
            req.power,
            cp=req.cp,
            w_prime=req.w_prime,
            dt_s=req.dt_s,
            duration_s=req.duration_s,
            tau_model=req.tau_model or "skiba_default",
            athlete_profile=req.athlete_profile,
        )
        usage = analyze_w_prime_usage(req.power, balance, w_prime=req.w_prime)
        return {"balance": balance, "usage": usage}

    def durability_index(self, req: DurabilityIndexRequest) -> Dict[str, Any]:
        return calculate_durability_index(req.power, duration_seconds=len(req.power))

    def np_drift(self, power: List[float]) -> Dict[str, Any]:
        return calculate_np_drift(power, len(power))

    def tte_sustainability(self, power: List[float], *, cp: float) -> Dict[str, Any]:
        return calculate_tte_sustainability(power, cp)

    def hourly_decay_curve(self, power: List[float], *, ftp: Optional[float] = None) -> Dict[str, Any]:
        del ftp  # API accepts FTP for future chart overlays; decay uses stream length.
        return generate_hourly_decay_curve(power, len(power))

    def durability_prescription(self, durability_index: float) -> Dict[str, Any]:
        if durability_index >= 97:
            classification = "EXCELLENT"
        elif durability_index >= 93:
            classification = "GOOD"
        elif durability_index >= 88:
            classification = "FAIR"
        else:
            classification = "POOR"
        return generate_durability_prescription(durability_index, classification)

    def cardiac(
        self,
        stream: Any,
        *,
        athlete: AthleteParams,
        metabolic_snapshot: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        samples = []
        for i in range(stream.n_samples):
            p, h = stream.power[i], stream.heart_rate[i]
            if p is None or h is None:
                continue
            samples.append(ActivitySample(t=float(stream.elapsed_s[i]), power=float(p), hr=float(h)))
        if not samples:
            return {"status": "error", "reason": "NO_VALID_SAMPLES"}
        ctx = athlete_context_from_params(athlete)
        analyzer = CardiacResponseAnalyzer(
            weight=athlete.weight_kg,
            context=ctx,
            metabolic_snapshot=metabolic_snapshot,
        )
        return analyzer.analyze(samples)

    def hrv_analyze(
        self,
        stream: Any,
        *,
        window_seconds: int = 120,
        step_seconds: Optional[float] = None,
        max_windows: int = 500,
    ) -> Dict[str, Any]:
        if not getattr(stream, "has_rr", False):
            return {"status": "error", "reason": "NO_RR_DATA"}
        rr_samples = [
            {"elapsed": float(stream.elapsed_s[i]), "rr": stream.rr_intervals[i]}
            for i in range(stream.n_samples)
            if stream.rr_intervals[i]
        ]
        if not rr_samples:
            return {"status": "error", "reason": "RR_INTERVALS_EMPTY"}

        duration_s = float(getattr(stream, "total_elapsed_s", 0) or getattr(stream, "n_samples", 0) or 0)
        base_step = 10.0 if step_seconds is None else max(1.0, float(step_seconds))
        adaptive_step = base_step
        expected_windows = 0
        if duration_s > float(window_seconds):
            expected_windows = int(max(0.0, duration_s - float(window_seconds)) / base_step) + 1
        if max_windows and expected_windows > int(max_windows):
            adaptive_step = max(
                base_step,
                (duration_s - float(window_seconds)) / max(float(int(max_windows) - 1), 1.0),
            )

        timeline = analyze_rr_stream(rr_samples, window_seconds=window_seconds, step_seconds=adaptive_step)
        tier = tier_for("hrv_engine")
        return {
            "status": "success",
            "timeline": timeline,
            "n_windows": len(timeline),
            "window_seconds": int(window_seconds),
            "step_seconds": round(float(adaptive_step), 3),
            "expected_windows_at_requested_step": expected_windows,
            "max_windows": int(max_windows) if max_windows else None,
            "adaptive_step_applied": bool(abs(float(adaptive_step) - float(base_step)) > 1e-9),
            "method": "dfa_alpha1",
            "tier": tier.value,
            "tier_explanation": tier.explanation,
        }

    def thermal_session(self, stream: Any, *, ftp: Optional[float]) -> Dict[str, Any]:
        n = int(getattr(stream, "n_samples", 0))
        report = analyze_thermal_session(
            core_temp_stream=[float(v or 0) for v in getattr(stream, "core_body_temp", [])[:n]],
            power_stream=power_list(stream),
            hr_stream=[float(h or 0) for h in stream.heart_rate[:n]],
            skin_temp_stream=[float(v or 0) for v in getattr(stream, "skin_temp", [])[:n]],
            ambient_temp_stream=[float(v or 0) for v in getattr(stream, "ambient_temp", [])[:n]],
            ftp=ftp,
        )
        return report.to_dict() if hasattr(report, "to_dict") else dict(report)

    def thermal_acclimation(self, sessions: List[Dict[str, Any]]) -> Dict[str, Any]:
        from engines.recovery.thermal_engine import HeatAcclimationTrend, ThermalSessionReport

        reports: List[ThermalSessionReport] = []
        for session in sessions:
            if isinstance(session, ThermalSessionReport):
                reports.append(session)
            elif isinstance(session, dict):
                reports.append(
                    ThermalSessionReport(
                        data_quality=str(session.get("data_quality") or "partial"),
                        n_valid_samples=int(session.get("n_valid_samples") or 0),
                        n_total_samples=int(session.get("n_total_samples") or 0),
                        thermal_rise_rate=session.get("thermal_rise_rate"),
                        heat_tolerance_threshold=session.get("heat_tolerance_threshold"),
                    )
                )
        trend = analyze_heat_acclimation(reports)
        return trend.to_dict() if isinstance(trend, HeatAcclimationTrend) else dict(trend)

    def pedaling_balance(self, stream: Any) -> Dict[str, Any]:
        n = int(getattr(stream, "n_samples", 0))
        balance = [
            float(v) if v is not None and v == v else None
            for v in getattr(stream, "left_right_balance", [])[:n]
        ]
        report = analyze_pedaling_balance(
            balance,
            power_list(stream),
            pedaling_balance_source=getattr(stream, "pedaling_balance_source", "unknown"),
        )
        return report.to_dict() if hasattr(report, "to_dict") else dict(report)

    def efforts(self, stream: Any, req: EffortsAnalyzeRequest) -> Dict[str, Any]:
        ftp = req.ftp or req.cp_w
        power = self.power_analyze(stream, weight_kg=req.athlete.weight_kg, ftp=ftp)
        if power.get("status") != "success":
            return power
        mmp = power.get("mmp_curve") or []
        cp_fit = power.get("critical_power")
        return analyze_efforts(
            mmp,
            weight_kg=req.athlete.weight_kg,
            ftp=req.cp_w,
            cp_fit=cp_fit,
            metabolic_snapshot=req.metabolic_snapshot,
        )

    def classify_session_ride(self, stream: Any, req: SessionClassifyRequest) -> Dict[str, Any]:
        result = classify_session(
            power_list(stream),
            filename=getattr(stream, "device_name", None),
            laps=list(getattr(stream, "laps", []) or []),
            ftp=req.ftp,
        )
        return result.to_dict() if hasattr(result, "to_dict") else dict(result)

    def protocol_completeness(self, stream: Any) -> Dict[str, Any]:
        n = len(power_list(stream))
        available = [d for d in (5, 15, 30, 60, 120, 300, 600, 1200, 1800, 3600) if n >= d]
        report = protocol_completeness(available_durations_s=available or [60])
        return report.to_dict() if hasattr(report, "to_dict") else dict(report)

    def session_route_decide(self, stream: Any, *, ftp: Optional[float]) -> Dict[str, Any]:
        power = power_list(stream)
        laps = list(getattr(stream, "laps", []) or [])
        decision = decide_route(
            power,
            filename=getattr(stream, "device_name", None),
            laps=laps,
            ftp=ftp,
            has_rr=getattr(stream, "has_rr", False),
            has_metabolic_profile=False,
        )
        return decision.to_dict() if hasattr(decision, "to_dict") else dict(decision)

    def session_route_run(
        self,
        stream: Any,
        *,
        athlete: AthleteParams,
        ftp: Optional[float],
        metabolic_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        ctx = athlete_context_from_params(athlete)
        rr = None
        if getattr(stream, "has_rr", False):
            rr = [
                {"elapsed": float(stream.elapsed_s[i]), "rr": stream.rr_intervals[i]}
                for i in range(stream.n_samples)
                if stream.rr_intervals[i]
            ]
        return route_and_run(
            power_list(stream),
            rr_samples=rr,
            elapsed_s=[float(stream.elapsed_s[i]) for i in range(stream.n_samples)],
            weight_kg=athlete.weight_kg,
            filename=getattr(stream, "device_name", None),
            laps=list(getattr(stream, "laps", []) or []),
            ftp=ftp,
            context=ctx,
            metabolic_snapshot=metabolic_snapshot,
        )

    def resilience(self, mader_durability: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return build_physiological_resilience(mader_durability=mader_durability)

    def metabolic_flexibility(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        fatmax = (
            snapshot.get("fatmax_power_watts")
            or snapshot.get("fatmax_watts")
            or snapshot.get("current_fatmax_watts")
        )
        vt2 = (
            snapshot.get("mlss_power_watts")
            or snapshot.get("vt2_watts")
            or snapshot.get("threshold_power_w")
        )
        if fatmax is None or vt2 is None:
            return {"status": "partial", "reason": "MISSING_FATMAX_OR_VT2"}
        return calculate_metabolic_flexibility_index(float(fatmax), float(vt2))

    def climb_segments(self, stream: Any) -> Dict[str, Any]:
        return detect_climb_segments(stream)

    def compare_segments(self, history: List[Dict[str, Any]], new_segments: List[Dict[str, Any]]) -> Dict[str, Any]:
        return compare_segments(history, new_segments)

    def adaptive_load(self, stream: Any, req: AdaptiveLoadRequest) -> Dict[str, Any]:
        summary = req.workout_summary
        if not summary:
            summary = build_workout_summary(
                stream,
                weight_kg=req.athlete.weight_kg,
                ftp=req.ftp,
                context=athlete_context_from_params(req.athlete),
            )
        profile = AthleteLoadProfile(weight_kg=req.athlete.weight_kg, ftp=req.ftp)
        daily = DailyStatus.from_dict(req.daily_status)
        return build_adaptive_load_report(
            stream=stream,
            workout_summary=summary,
            athlete_profile=profile,
            daily_status=daily,
            history=req.history,
        )
