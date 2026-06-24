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
        return result if result else {"status": "error", "reason": "FIT_FAILED"}

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
        return calculate_np_drift(power)

    def tte_sustainability(self, power: List[float], *, cp: float) -> Dict[str, Any]:
        return calculate_tte_sustainability(power, cp_w=cp)

    def hourly_decay_curve(self, power: List[float], *, ftp: float) -> Dict[str, Any]:
        return generate_hourly_decay_curve(power, ftp=ftp)

    def durability_prescription(self, durability_index: float) -> Dict[str, Any]:
        return generate_durability_prescription(durability_index)

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
        step_seconds: float = 10.0,
    ) -> Dict[str, Any]:
        if not getattr(stream, "has_rr", False):
            return {"status": "error", "reason": "NO_RR_DATA"}
        rr_samples = [
            {"elapsed": float(stream.elapsed_s[i]), "rr": stream.rr_intervals[i]}
            for i in range(stream.n_samples)
            if stream.rr_intervals[i]
        ]
        timeline = analyze_rr_stream(rr_samples, window_seconds=window_seconds, step_seconds=step_seconds)
        return {"status": "success", "timeline": timeline, "n_windows": len(timeline)}

    def thermal_session(self, stream: Any, *, ftp: Optional[float]) -> Dict[str, Any]:
        n = int(getattr(stream, "n_samples", 0))
        return analyze_thermal_session(
            core_temp_stream=[float(v or 0) for v in getattr(stream, "core_body_temp", [])[:n]],
            power_stream=power_list(stream),
            hr_stream=[float(h or 0) for h in stream.heart_rate[:n]],
            skin_temp_stream=[float(v or 0) for v in getattr(stream, "skin_temp", [])[:n]],
            ambient_temp_stream=[float(v or 0) for v in getattr(stream, "ambient_temp", [])[:n]],
            ftp=ftp,
        )

    def thermal_acclimation(self, sessions: List[Dict[str, Any]]) -> Dict[str, Any]:
        return analyze_heat_acclimation(sessions)

    def pedaling_balance(self, stream: Any) -> Dict[str, Any]:
        return analyze_pedaling_balance(stream)

    def efforts(self, stream: Any, req: EffortsAnalyzeRequest) -> Dict[str, Any]:
        power = self.power_analyze(stream, weight_kg=req.athlete.weight_kg, ftp=None)
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
        return classify_session(stream, ftp=req.ftp, weight_kg=req.athlete.weight_kg)

    def protocol_completeness(self, stream: Any) -> Dict[str, Any]:
        return protocol_completeness(stream)

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
        return calculate_metabolic_flexibility_index(snapshot)

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
