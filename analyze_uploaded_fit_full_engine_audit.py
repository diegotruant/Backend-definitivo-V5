#!/usr/bin/env python3
"""Run every available backend engine over uploaded FIT files, excluding GPX race prediction."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

import numpy as np

from engines import (
    AthleteContext,
    DailyInput,
    MetabolicProfiler,
    analyze_rr_stream,
    analyze_heat_acclimation,
    analyze_pedaling_balance,
    analyze_thermal_session,
    analyze_w_prime_usage,
    apply_detraining_model,
    assess_data_quality,
    bayesian_metabolic_snapshot,
    build_workout_summary,
    calculate_acwr,
    calculate_ctl_atl_tsb,
    calculate_durability_index,
    calculate_metabolic_flexibility_index,
    calculate_monotony_strain,
    calculate_np_drift,
    calculate_w_prime_balance,
    classify_session,
    cross_validate_metabolic_profile,
    curve_to_mmp,
    estimate_fat_oxidation_rate,
    generate_acwr_narrative,
    generate_hourly_decay_curve,
    compute_session_durability,
    get_current_metabolic_status,
    parse_fit_file_enhanced,
    process_workout_history,
    update_power_curve,
)
from engines.recovery.cardiac_engine import ActivitySample, CardiacResponseAnalyzer
from engines.recovery.explainability_engine import calculate_vo2max_confidence, generate_workout_summary_narrative
from engines.io.chart_builder import chart_power_duration_curve, chart_training_load
from engines.metabolic.coggan_classifier import classify_from_mmp
from engines.performance.efforts_analyzer import analyze_efforts
from engines.performance.mmp_quality import analyze_mmp_quality, clean_mmp
from engines.performance.neural_ode import NeuralDynamics, NeuralPowerDuration
from engines.performance.power_engine import PowerEngine, estimate_ftp_from_mmp, fit_critical_power, mean_maximal_power
from engines.metabolic.zones_engine import ZonesEngine


UPLOAD_ROOT = Path("data/fit_uploads")
OUTPUT_DIR = Path("reports/uploaded_fit_full_engine_audit")
WEIGHT_KG = 75.0
W_PRIME_TAU_S = 546.0
LAB_UPLOAD_ROOT = Path("data/lab_uploads")


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fields)
        writer.writeheader()
        writer.writerows(rows)


def grouped_fit_files() -> Dict[str, List[Path]]:
    grouped: Dict[str, List[Path]] = defaultdict(list)
    for archive_root in sorted(p for p in UPLOAD_ROOT.iterdir() if p.is_dir()):
        for fit_path in sorted(list(archive_root.rglob("*.fit")) + list(archive_root.rglob("*.FIT"))):
            rel = fit_path.relative_to(archive_root)
            athlete = rel.parts[0] if len(rel.parts) > 1 else archive_root.name
            grouped[athlete].append(fit_path)
    return dict(sorted(grouped.items()))


def engine_row(
    athlete: str,
    engine: str,
    status: str,
    *,
    scope: str = "athlete",
    successes: int = 0,
    skipped: int = 0,
    errors: int = 0,
    key_output: Any = "",
    warning: str = "",
) -> Dict[str, Any]:
    return {
        "athlete": athlete,
        "engine": engine,
        "scope": scope,
        "status": status,
        "successes": successes,
        "skipped": skipped,
        "errors": errors,
        "key_output": json.dumps(key_output, default=str) if not isinstance(key_output, str) else key_output,
        "warning": warning,
    }


def safe_call(fn: Callable[[], Any]) -> Tuple[str, Any, str]:
    try:
        return "success", fn(), ""
    except Exception as exc:  # audit runner must continue across engines
        return "error", None, f"{type(exc).__name__}: {exc}"


def stream_arrays(stream) -> Tuple[List[float], List[float], List[float]]:
    power = [float(v) for v in stream.power]
    hr = [float(v) for v in stream.heart_rate]
    cadence = [float(v) for v in stream.cadence]
    return power, hr, cadence


def first_date_or_today(streams: List[Any]) -> date:
    dates = [s.start_time.date() for _, s in streams if getattr(s, "start_time", None)]
    return min(dates) if dates else date.today()


def estimate_w_prime_joules(cp_w: float) -> float:
    """Heuristic W' capacity when no formal test is available (audit default)."""
    return float(np.clip(cp_w * 90.0, 15000.0, 35000.0))


def athlete_has_lab_files(athlete: str) -> bool:
    if not LAB_UPLOAD_ROOT.is_dir():
        return False
    for path in LAB_UPLOAD_ROOT.rglob("*"):
        if path.is_file() and path.suffix.lower() in (".pdf", ".txt", ".csv"):
            if athlete.lower() in str(path).lower():
                return True
    return False


def analyze_athlete(athlete: str, files: List[Path]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    matrix: List[Dict[str, Any]] = []
    activity_rows: List[Dict[str, Any]] = []
    error_rows: List[Dict[str, Any]] = []
    parsed: List[Tuple[Path, Any]] = []

    for fit_path in files:
        status, stream, err = safe_call(lambda p=fit_path: parse_fit_file_enhanced(str(p)))
        if status == "success":
            parsed.append((fit_path, stream))
        else:
            error_rows.append({"athlete": athlete, "file": fit_path.name, "engine": "fit_parser", "error": err})
    matrix.append(engine_row(athlete, "fit_parser", "success" if len(parsed) == len(files) else "warning",
                             scope="activity", successes=len(parsed), errors=len(files) - len(parsed)))

    aggregate_mmp: Dict[int, float] = {}
    stored_curve: Dict[int, Dict[str, Any]] = {}
    activity_tss: List[float] = []
    workout_history: List[Dict[str, Any]] = []
    daily_inputs: List[DailyInput] = []
    thermal_reports = []
    balance_reports = []
    hrv_success = hrv_warning = cardiac_success = 0
    hrv_skipped = cardiac_skipped = 0
    balance_success = balance_skipped = 0
    thermal_success = thermal_skipped = 0
    wprime_success = wprime_skipped = 0
    explain_success = explain_skipped = 0
    per_engine_counts: Counter[str] = Counter()
    per_engine_errors: Counter[str] = Counter()

    # First pass: aggregate MMP and estimate FTP.
    for fit_path, stream in parsed:
        if stream.has_power:
            mmp = mean_maximal_power(np.asarray(stream.power, dtype=float))
            for point in mmp:
                d = int(point["duration_s"])
                aggregate_mmp[d] = max(aggregate_mmp.get(d, 0.0), float(point["power_w"]))
    mmp_curve = [{"duration_s": d, "power_w": p, "wkg": round(p / WEIGHT_KG, 2)} for d, p in sorted(aggregate_mmp.items())]
    cp_fit = fit_critical_power(mmp_curve)
    ftp_info = estimate_ftp_from_mmp(mmp_curve, cp_fit.get("cp_w") if cp_fit else None)
    ftp = float(ftp_info.get("ftp_w") or 250.0)
    cp_w = float(cp_fit.get("cp_w") if cp_fit else ftp)
    w_prime_j = estimate_w_prime_joules(cp_w)

    metabolic_snapshot: Dict[str, Any] = {}
    metabolic_profiler_status = "skipped_no_mmp"
    profiler = MetabolicProfiler(weight=WEIGHT_KG, context=AthleteContext())
    if len(aggregate_mmp) >= 3:
        status, metabolic_snapshot, err = safe_call(lambda: profiler.generate_metabolic_snapshot(aggregate_mmp))
        metabolic_profiler_status = status if status == "error" else metabolic_snapshot.get("status", status)
        if err:
            error_rows.append({"athlete": athlete, "file": "", "engine": "metabolic_profiler", "error": err})

    # Per-activity engines.
    for fit_path, stream in parsed:
        power, hr, cadence = stream_arrays(stream)
        row = {"athlete": athlete, "file": fit_path.name}

        status, quality, err = safe_call(lambda: assess_data_quality(power, hr if stream.has_heart_rate else None, cadence))
        if status == "success":
            row["data_quality"] = round(float(quality.overall_score), 3)
            per_engine_counts["data_quality_engine"] += 1
        else:
            per_engine_errors["data_quality_engine"] += 1
            error_rows.append({"athlete": athlete, "file": fit_path.name, "engine": "data_quality_engine", "error": err})

        if stream.has_power:
            status, power_result, err = safe_call(lambda: PowerEngine(ftp=ftp, weight_kg=WEIGHT_KG).analyze(stream))
            if status == "success" and power_result.get("status") == "success":
                metrics = power_result["metrics"]
                row.update({
                    "tss": metrics.get("tss"),
                    "normalized_power": metrics.get("normalized_power"),
                    "intensity_factor": metrics.get("intensity_factor"),
                })
                activity_tss.append(float(metrics.get("tss") or 0.0))
                workout_history.append({
                    "date": stream.start_time.date() if stream.start_time else first_date_or_today(parsed),
                    "tss": float(metrics.get("tss") or 0.0),
                })
                per_engine_counts["power_engine"] += 1
            else:
                per_engine_errors["power_engine"] += 1
                error_rows.append({"athlete": athlete, "file": fit_path.name, "engine": "power_engine", "error": err or str(power_result)})

            status, curve_update, err = safe_call(lambda: update_power_curve(
                power,
                stream.start_time.date().isoformat() if stream.start_time else "unknown",
                stored_curve,
                fit_path.name,
                weight_kg=WEIGHT_KG,
            ))
            if status == "success":
                stored_curve = curve_update.curve
                per_engine_counts["mmp_aggregator"] += 1
            else:
                per_engine_errors["mmp_aggregator"] += 1
                error_rows.append({"athlete": athlete, "file": fit_path.name, "engine": "mmp_aggregator", "error": err})

            status, cls, err = safe_call(lambda: classify_session(power, filename=fit_path.name, ftp=ftp))
            if status == "success":
                row["category"] = cls.category
                row["subtype"] = cls.subtype
                per_engine_counts["interval_detector"] += 1
                sv = cls.stimulus_vector.to_dict() if cls.stimulus_vector else {}
                anchors = [(a.duration_s, a.power_w) for a in cls.qualified_anchors]
                daily_inputs.append(DailyInput(
                    date=stream.start_time.date() if stream.start_time else first_date_or_today(parsed),
                    vo2max_stimulus_min=float(sv.get("vo2max_min") or 0.0),
                    threshold_stimulus_min=float(sv.get("threshold_min") or 0.0),
                    anaerobic_stimulus_min=float(sv.get("anaerobic_min") or 0.0),
                    neuromuscular_stimulus_min=float(sv.get("neuromuscular_min") or 0.0),
                    test_anchors=anchors or None,
                ))
            else:
                per_engine_errors["interval_detector"] += 1
                error_rows.append({"athlete": athlete, "file": fit_path.name, "engine": "interval_detector", "error": err})

            # Several per-activity engines.
            workout_summary_result: Dict[str, Any] = {}
            engine_calls = {
                "durability_engine": lambda: calculate_durability_index(power, int(stream.total_elapsed_s or len(power))),
                "np_drift": lambda: calculate_np_drift(power, int(stream.total_elapsed_s or len(power))),
                "hourly_decay_curve": lambda: generate_hourly_decay_curve(power, int(stream.total_elapsed_s or len(power))),
                "zones_engine": lambda: ZonesEngine(ftp=ftp).analyze(stream),
                "workout_summary": lambda: build_workout_summary(stream, weight_kg=WEIGHT_KG, ftp=ftp, metabolic_snapshot=metabolic_snapshot),
            }
            for engine, fn in engine_calls.items():
                status, result, err = safe_call(fn)
                if status == "success":
                    per_engine_counts[engine] += 1
                    if engine == "workout_summary" and isinstance(result, dict):
                        workout_summary_result = result
                else:
                    per_engine_errors[engine] += 1
                    error_rows.append({"athlete": athlete, "file": fit_path.name, "engine": engine, "error": err})

            if metabolic_snapshot.get("status") == "success" and power:
                status_md, mader_result, err_md = safe_call(
                    lambda: compute_session_durability(
                        power, metabolic_snapshot, weight_kg=WEIGHT_KG,
                    )
                )
                if status_md == "success" and mader_result.get("status") == "success":
                    per_engine_counts["mader_durability"] += 1
                    row["mader_durability_loss_pct"] = mader_result.get("durability_loss_pct")
                elif status_md == "success" and mader_result.get("status") in (
                    "unavailable", "insufficient_data",
                ):
                    per_engine_counts["mader_durability"] += 1
                else:
                    per_engine_errors["mader_durability"] += 1
                    error_rows.append({
                        "athlete": athlete,
                        "file": fit_path.name,
                        "engine": "mader_durability",
                        "error": err_md or str(mader_result),
                    })
            status, w_balance, err = safe_call(
                lambda: calculate_w_prime_balance(power, cp=cp_w, w_prime=w_prime_j, tau=W_PRIME_TAU_S)
            )
            if status == "success" and w_balance:
                status_u, w_usage, err_u = safe_call(
                    lambda: analyze_w_prime_usage(power, w_balance, w_prime=w_prime_j)
                )
                if status_u == "success":
                    wprime_success += 1
                    row["w_prime_min_pct"] = w_usage.get("min_balance_pct")
                    per_engine_counts["w_prime_balance_engine"] += 1
                else:
                    per_engine_errors["w_prime_balance_engine"] += 1
                    error_rows.append({"athlete": athlete, "file": fit_path.name, "engine": "w_prime_balance_engine", "error": err_u})
            else:
                per_engine_errors["w_prime_balance_engine"] += 1
                error_rows.append({"athlete": athlete, "file": fit_path.name, "engine": "w_prime_balance_engine", "error": err})

            if workout_summary_result.get("status") == "success":
                status_n, narrative, err_n = safe_call(
                    lambda: generate_workout_summary_narrative(workout_summary_result)
                )
                if status_n == "success" and narrative:
                    explain_success += 1
                    row["narrative_chars"] = len(narrative)
                    per_engine_counts["explainability_engine"] += 1
                else:
                    per_engine_errors["explainability_engine"] += 1
                    error_rows.append({"athlete": athlete, "file": fit_path.name, "engine": "explainability_engine", "error": err_n})
            else:
                explain_skipped += 1

            if stream.has_heart_rate and stream.has_power:
                samples = [
                    ActivitySample(t=float(i), power=float(power[i]), hr=float(hr[i]))
                    for i in range(min(len(power), len(hr)))
                    if hr[i] > 0
                ]
                if len(samples) >= 60:
                    status_c, cardiac, err_c = safe_call(
                        lambda: CardiacResponseAnalyzer(
                            weight=WEIGHT_KG,
                            metabolic_snapshot=metabolic_snapshot if metabolic_snapshot.get("status") == "success" else None,
                        ).analyze(samples)
                    )
                    if status_c == "success" and cardiac.get("status") == "success":
                        cardiac_success += 1
                        row["cardiac_fitness_class"] = (cardiac.get("summary") or {}).get("fitness_class")
                        per_engine_counts["cardiac_engine"] += 1
                    else:
                        cardiac_skipped += 1
                        if status_c == "error" or cardiac.get("status") != "success":
                            per_engine_errors["cardiac_engine"] += 1
                            error_rows.append({"athlete": athlete, "file": fit_path.name, "engine": "cardiac_engine", "error": err_c or str(cardiac)})
                else:
                    cardiac_skipped += 1
            else:
                cardiac_skipped += 1
        else:
            cardiac_skipped += 1
            wprime_skipped += 1
            explain_skipped += 1

        # Optional-data engines: HRV from record rr_intervals or FIT hrv messages.
        if stream.has_rr:
            rr_samples = [
                {"elapsed": float(stream.elapsed_s[i]), "rr": stream.rr_intervals[i]}
                for i in range(stream.n_samples)
                if stream.rr_intervals[i]
            ]
            status, timeline, err = safe_call(
                lambda: analyze_rr_stream(rr_samples, context=AthleteContext())
            )
            if status == "success" and timeline:
                hrv_success += 1
                row["hrv_windows"] = len(timeline)
                per_engine_counts["hrv_engine"] += 1
            elif status == "success":
                hrv_warning += 1
                row["hrv_windows"] = 0
                per_engine_errors["hrv_engine"] += 1
                error_rows.append({
                    "athlete": athlete,
                    "file": fit_path.name,
                    "engine": "hrv_engine",
                    "error": "RR present but DFA produced no valid windows",
                })
            else:
                per_engine_errors["hrv_engine"] += 1
                error_rows.append({"athlete": athlete, "file": fit_path.name, "engine": "hrv_engine", "error": err})
        else:
            hrv_skipped += 1

        status, thermal, err = safe_call(lambda: analyze_thermal_session(
            [float(v) if v == v else None for v in stream.core_body_temp],
            power,
            hr_stream=hr if stream.has_heart_rate else None,
            skin_temp_stream=[float(v) if v == v else None for v in stream.skin_temp],
            ambient_temp_stream=[float(v) if v == v else None for v in stream.ambient_temp],
            ftp=ftp,
        ))
        if status == "success":
            thermal_reports.append(thermal)
            if thermal.data_quality == "no_data":
                thermal_skipped += 1
            else:
                thermal_success += 1
        else:
            per_engine_errors["thermal_engine"] += 1
            error_rows.append({"athlete": athlete, "file": fit_path.name, "engine": "thermal_engine", "error": err})

        status, balance, err = safe_call(lambda: analyze_pedaling_balance(
            [float(v) if v == v else None for v in stream.left_right_balance],
            power,
            ftp=ftp,
            pedaling_balance_source=stream.pedaling_balance_source,
        ))
        if status == "success":
            balance_reports.append(balance)
            if balance.data_quality in ("good", "partial"):
                balance_success += 1
            else:
                balance_skipped += 1
        else:
            per_engine_errors["pedaling_balance"] += 1
            error_rows.append({"athlete": athlete, "file": fit_path.name, "engine": "pedaling_balance", "error": err})

        activity_rows.append(row)

    # Athlete-level engines.
    for engine in (
        "data_quality_engine",
        "power_engine",
        "interval_detector",
        "durability_engine",
        "np_drift",
        "hourly_decay_curve",
        "zones_engine",
        "workout_summary",
        "mader_durability",
    ):
        successes = per_engine_counts[engine]
        errors = per_engine_errors[engine]
        skipped = len(parsed) - successes - errors
        if successes:
            status = "success" if errors == 0 else "warning"
        elif skipped:
            status = "skipped_no_required_data"
        else:
            status = "error"
        matrix.append(engine_row(
            athlete,
            engine,
            status,
            scope="activity",
            successes=successes,
            skipped=skipped,
            errors=errors,
        ))

    mmp_for_profiler = curve_to_mmp(stored_curve) or aggregate_mmp
    clean_status, clean_result, clean_err = safe_call(lambda: clean_mmp(mmp_for_profiler))
    mmp_quality_status, mmp_quality, mmp_quality_err = safe_call(lambda: analyze_mmp_quality(mmp_for_profiler))
    matrix.append(engine_row(athlete, "mmp_quality", mmp_quality_status, key_output=getattr(mmp_quality, "overall_quality", "")))
    matrix.append(engine_row(athlete, "mmp_aggregator", "success" if stored_curve else "skipped_no_power",
                             successes=per_engine_counts["mmp_aggregator"],
                             key_output={"mmp_points": len(mmp_for_profiler)}))
    matrix.append(engine_row(athlete, "metabolic_profiler", metabolic_profiler_status,
                             key_output={
                                 "vo2max": metabolic_snapshot.get("estimated_vo2max"),
                                 "vlamax": metabolic_snapshot.get("estimated_vlamax_mmol_L_s"),
                                 "mlss": metabolic_snapshot.get("mlss_power_watts"),
                             }))

    # Coggan classifier, efforts, charts, metabolic flexibility.
    status, coggan, err = safe_call(lambda: classify_from_mmp(mmp_curve, WEIGHT_KG, "MALE", ftp=ftp))
    matrix.append(engine_row(athlete, "coggan_classifier", status, key_output=coggan.get("overall", {}) if coggan else "", warning=err))
    status, efforts, err = safe_call(lambda: analyze_efforts(mmp_curve, WEIGHT_KG, ftp=ftp, cp_fit=cp_fit, metabolic_snapshot=metabolic_snapshot))
    matrix.append(engine_row(athlete, "efforts_analyzer", status, key_output={"efforts": len(efforts.get("efforts", []))} if efforts else "", warning=err))
    status, chart, err = safe_call(lambda: chart_power_duration_curve(mmp_for_profiler, cp_model=None, ftp=ftp))
    matrix.append(engine_row(athlete, "chart_builder", status, key_output=chart.get("type") if chart else "", warning=err))

    fatmax = metabolic_snapshot.get("fatmax_power_watts")
    mlss = metabolic_snapshot.get("mlss_power_watts")
    if fatmax and mlss:
        matrix.append(engine_row(athlete, "metabolic_flexibility_engine", "success", key_output={
            "mfi": calculate_metabolic_flexibility_index(float(fatmax), float(mlss)).get("mfi"),
            "fat_ox": estimate_fat_oxidation_rate(float(fatmax), WEIGHT_KG).get("fat_oxidation_g_per_min"),
        }))
    else:
        matrix.append(engine_row(athlete, "metabolic_flexibility_engine", "skipped_missing_metabolic_fields"))

    # Cross-validation.
    unmasked = metabolic_snapshot.get("unmasked_estimates", {})
    vo2 = unmasked.get("estimated_vo2max") or metabolic_snapshot.get("estimated_vo2max")
    vla = unmasked.get("estimated_vlamax_mmol_L_s") or metabolic_snapshot.get("estimated_vlamax_mmol_L_s")
    cv_embedded = metabolic_snapshot.get("cross_validation") if metabolic_snapshot else None
    if cv_embedded:
        matrix.append(engine_row(
            athlete,
            "cross_validation_engine",
            "success" if cv_embedded.get("coherent") else "warning",
            key_output=cv_embedded,
        ))
    elif vo2 is not None and vla is not None and len(mmp_for_profiler) >= 3:
        resolved_eta = float(
            (metabolic_snapshot.get("context_used") or {}).get("resolved_eta") or 0.23
        )
        status, cv, err = safe_call(lambda: cross_validate_metabolic_profile(
            profiler,
            mmp_for_profiler,
            float(vo2),
            float(vla),
            eta_base=resolved_eta,
        ))
        matrix.append(engine_row(athlete, "cross_validation_engine", status if status == "error" else ("success" if cv.coherent else "warning"),
                                 key_output=cv.to_dict() if cv else "", warning=err))
    else:
        matrix.append(engine_row(athlete, "cross_validation_engine", "skipped_missing_metabolic_fields"))

    # Bayesian profiler (short chain for audit runtime).
    if len(mmp_for_profiler) >= 3:
        status, bayes, err = safe_call(lambda: bayesian_metabolic_snapshot(
            MetabolicProfiler(weight=WEIGHT_KG), mmp_for_profiler, n_samples=800, n_warmup=200, seed=7
        ).to_dict())
        matrix.append(engine_row(athlete, "bayesian_profiler", status if status == "error" else bayes.get("status", status),
                                 key_output={"confidence": bayes.get("bayesian_confidence")} if bayes else "", warning=err))
    else:
        matrix.append(engine_row(athlete, "bayesian_profiler", "skipped_no_mmp"))

    # Kalman, detraining, current status and training variability.
    if vo2 is not None and vla is not None and daily_inputs:
        status, traj, err = safe_call(lambda: process_workout_history(
            sorted(daily_inputs, key=lambda di: di.date),
            initial_vo2=float(vo2),
            initial_vla=float(vla),
            weight=WEIGHT_KG,
            athlete_id=athlete,
            profiler=MetabolicProfiler(weight=WEIGHT_KG),
        ))
        matrix.append(engine_row(athlete, "metabolic_kalman", status, key_output=traj.to_dict().get("final_state") if traj else "", warning=err))
    else:
        matrix.append(engine_row(athlete, "metabolic_kalman", "skipped_missing_state_or_inputs"))

    today = max([w["date"] for w in workout_history], default=date.today())
    if workout_history:
        tl = calculate_ctl_atl_tsb(workout_history, today)
        acwr_payload = calculate_acwr(tl["atl"], tl["ctl"])
        monotony_payload = calculate_monotony_strain(
            activity_tss[-7:] if len(activity_tss) >= 7 else activity_tss
        )
        matrix.append(engine_row(athlete, "training_variability_engine", "success", key_output={
            "acwr": acwr_payload.get("acwr"),
            "monotony": monotony_payload.get("monotony"),
        }))
        if acwr_payload.get("status") == "success":
            status_n, acwr_text, err_n = safe_call(
                lambda: generate_acwr_narrative(
                    float(acwr_payload["acwr"]),
                    str(acwr_payload.get("risk_level", "UNKNOWN")),
                    float(tl["ctl"]),
                    float(tl["atl"]),
                    float(tl["tsb"]),
                )
            )
            if status_n == "success" and acwr_text:
                per_engine_counts["explainability_engine"] += 1
            elif status_n == "error":
                error_rows.append({"athlete": athlete, "file": "", "engine": "explainability_engine_acwr", "error": err_n})
        if len(mmp_for_profiler) >= 3:
            status_v, vo2_conf, err_v = safe_call(
                lambda: calculate_vo2max_confidence(
                    mmp_for_profiler,
                    efforts_count=len(parsed),
                    data_quality_score=float(np.mean([r.get("data_quality", 0.8) for r in activity_rows if r.get("athlete") == athlete]) or 0.8),
                )
            )
            if status_v == "success" and vo2_conf:
                per_engine_counts["explainability_engine"] += 1
        status, detraining, err = safe_call(lambda: apply_detraining_model(metabolic_snapshot, workout_history, today))
        matrix.append(engine_row(athlete, "detraining_engine", status if status == "error" else detraining.get("status", status),
                                 key_output=detraining.get("training_load", {}) if detraining else "", warning=err))
        status, current, err = safe_call(lambda: get_current_metabolic_status(mmp_for_profiler, workout_history, WEIGHT_KG, today=today))
        matrix.append(engine_row(athlete, "metabolic_current", status if status == "error" else current.get("status", status),
                                 key_output={k: current.get(k) for k in ("current_vo2max", "current_mlss_watts")} if current else "", warning=err))
        status, load_chart, err = safe_call(lambda: chart_training_load([w["date"] for w in workout_history], [tl["ctl"]] * len(workout_history), [tl["atl"]] * len(workout_history), [tl["tsb"]] * len(workout_history)))
        matrix.append(engine_row(athlete, "chart_builder_training_load", status, key_output=load_chart.get("type") if load_chart else "", warning=err))
    else:
        for engine in ("training_variability_engine", "detraining_engine", "metabolic_current", "chart_builder_training_load"):
            matrix.append(engine_row(athlete, engine, "skipped_no_workout_history"))

    # Neural ODE smoke: untrained prediction/dynamics are still engine outputs.
    if vo2 is not None and vla is not None and aggregate_mmp:
        durations = np.array(sorted(list(aggregate_mmp))[:5], dtype=float)
        observed = np.array([aggregate_mmp[int(d)] for d in durations], dtype=float)
        status, neural_pred, err = safe_call(lambda: NeuralPowerDuration().predict(durations, observed, float(vo2), float(vla)))
        status_dyn, delta, err_dyn = safe_call(lambda: NeuralDynamics().predict_delta(float(vo2), float(vla), 0.0, 0.0))
        matrix.append(engine_row(athlete, "neural_ode", "success" if status == status_dyn == "success" else "error",
                                 key_output={"pd_points": len(neural_pred) if neural_pred is not None else 0, "delta": delta.tolist() if hasattr(delta, "tolist") else delta},
                                 warning=err or err_dyn))
    else:
        matrix.append(engine_row(athlete, "neural_ode", "skipped_missing_metabolic_fields"))

    # Optional data summaries.
    if hrv_success:
        hrv_status = "success"
    elif hrv_warning:
        hrv_status = "warning"
    elif hrv_skipped and not hrv_warning:
        hrv_status = "skipped_no_rr"
    else:
        hrv_status = "skipped_no_rr"
    matrix.append(engine_row(athlete, "hrv_engine", hrv_status,
                             scope="activity", successes=hrv_success, skipped=hrv_skipped,
                             warning=f"{hrv_warning} activities with RR but no DFA windows" if hrv_warning else ""))
    matrix.append(engine_row(athlete, "w_prime_balance_engine", "success" if wprime_success else "skipped_no_power",
                             scope="activity", successes=wprime_success, skipped=len(parsed) - wprime_success,
                             key_output={"cp_w": round(cp_w, 1), "w_prime_j": round(w_prime_j, 0)}))
    matrix.append(engine_row(athlete, "explainability_engine", "success" if explain_success else "skipped_no_workout_summary",
                             scope="activity", successes=explain_success, skipped=explain_skipped))
    matrix.append(engine_row(athlete, "cardiac_engine", "success" if cardiac_success else "skipped_missing_power_or_hr",
                             scope="activity", successes=cardiac_success, skipped=cardiac_skipped))
    matrix.append(engine_row(athlete, "thermal_engine", "success" if thermal_success else "skipped_no_body_temperature",
                             scope="activity", successes=thermal_success, skipped=thermal_skipped))
    matrix.append(engine_row(athlete, "pedaling_balance", "success" if balance_success else "skipped_no_balance",
                             scope="activity", successes=balance_success, skipped=balance_skipped))
    status, trend, err = safe_call(lambda: analyze_heat_acclimation(thermal_reports))
    matrix.append(engine_row(athlete, "heat_acclimation", status if thermal_success else "skipped_no_body_temperature",
                             key_output=trend.to_dict() if hasattr(trend, "to_dict") else "", warning=err))

    if athlete_has_lab_files(athlete):
        matrix.append(engine_row(athlete, "lab_data", "skipped_not_wired",
                                 warning="Lab files present under data/lab_uploads but batch parse not implemented in audit"))
    else:
        matrix.append(engine_row(athlete, "lab_data", "skipped_no_lab_file"))
    matrix.append(engine_row(athlete, "race_prediction_engine", "skipped_no_gpx",
                             warning="Requires GPX course file, not FIT upload"))

    return matrix, activity_rows, error_rows


def write_markdown(path: Path, matrix: List[Dict[str, Any]], errors: List[Dict[str, Any]]) -> None:
    by_engine = defaultdict(Counter)
    for row in matrix:
        by_engine[row["engine"]][row["status"]] += 1
    lines = [
        "# Uploaded FIT full engine audit",
        "",
        "Race prediction requires GPX course input (marked skipped_no_gpx).",
        "Lab ingestion requires files under data/lab_uploads/ (optional).",
        "W' balance uses CP from MMP fit and a heuristic W' capacity (CP × 90 s, clamped).",
        "",
        "## Engine status summary",
        "",
        "| Engine | Status counts |",
        "| --- | --- |",
    ]
    for engine in sorted(by_engine):
        lines.append(f"| {engine} | {dict(by_engine[engine])} |")
    lines.extend(["", "## Exceptions", ""])
    if errors:
        for err in errors:
            lines.append(f"- `{err['athlete']}/{err.get('file','')}` `{err['engine']}`: {err['error']}")
    else:
        lines.append("No backend exceptions detected.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    all_matrix: List[Dict[str, Any]] = []
    all_activities: List[Dict[str, Any]] = []
    all_errors: List[Dict[str, Any]] = []
    grouped = grouped_fit_files()
    for i, (athlete, files) in enumerate(grouped.items(), 1):
        print(f"[{i:02d}/{len(grouped)}] {athlete} ({len(files)} FIT)")
        matrix, activities, errors = analyze_athlete(athlete, files)
        all_matrix.extend(matrix)
        all_activities.extend(activities)
        all_errors.extend(errors)

    write_csv(OUTPUT_DIR / "engine_matrix.csv", all_matrix)
    write_csv(OUTPUT_DIR / "activity_engine_details.csv", all_activities)
    write_csv(OUTPUT_DIR / "errors.csv", all_errors)
    write_markdown(OUTPUT_DIR / "README.md", all_matrix, all_errors)
    print(f"Wrote {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
