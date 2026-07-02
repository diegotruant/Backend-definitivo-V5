"""
Workout Summary Orchestrator
Version: 1.0.0

Single per-activity entry point that combines all engines into one cohesive
report: a coach can ingest one FIT file, set FTP / LTHR / weight, optionally
provide an existing metabolic snapshot or HRV timeline, and get back a
complete summary covering:

  - Power metrics (FTP/NP/IF/TSS/VI/MMP, sprints, CP+W')
  - Metabolic MLSS power zones (time-in-zone, 5 buckets from snapshot)
  - Coggan power zones (time-in-zone, 7 buckets)
  - Friel HR zones (time-in-zone, 7 buckets)
  - Seiler 3-zone polarization (VT1/VT2 default from MLSS when snapshot present)
  - Coggan rider phenotype classification
  - DFA-α₁ analysis (if RR data present)
  - Cardiac response analysis (drift, decoupling, recovery, kinetics, ...)
  - Cross-validation against metabolic thresholds

This module is purely an orchestrator: it does not implement any new
calculations, only delegation. It is the single function that the
Supabase service layer should call after FIT ingestion.
"""

from typing import Any, Dict, List, Optional

# Flat imports — do not import via `engines.*` here; this module is loaded
# while `engines/__init__.py` may still be initialising.
from engines.core.athlete_context import AthleteContext
from engines.core.science_contracts import (
    cadence_anchor_metadata,
    derive_effective_cadence_rpm,
    enrich_metabolic_snapshot_cadence,
)
from engines.recovery.cardiac_engine import CardiacResponseAnalyzer, ActivitySample
from engines.metabolic.coggan_classifier import classify_from_mmp
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from engines.performance.power_engine import PowerEngine, estimate_ftp_from_mmp
from engines.metabolic.zones_engine import ZonesEngine
# hrv_engine imported lazily inside build_workout_summary() (see section 4).
from engines.core.metric_contracts import annotate_payload, summarize_section_contracts
from engines.core.tiers import tier_for
from engines.performance.physiological_resilience import build_physiological_resilience
from engines.io.activity_statistics import compute_activity_statistics
from engines.metabolic.fatmax_engine import build_model_fatmax_report


def _mmp_curve_to_dict(mmp_curve: List[Dict[str, Any]]) -> Dict[int, float]:
    out: Dict[int, float] = {}
    for row in mmp_curve or []:
        dur = row.get("duration_s")
        power = row.get("power_w")
        if dur is None or power is None:
            continue
        try:
            out[int(dur)] = float(power)
        except (TypeError, ValueError):
            continue
    return out


def build_workout_summary(
    stream,
    weight_kg: float,
    ftp: Optional[float] = None,
    lthr: Optional[float] = None,
    context: Optional[AthleteContext] = None,
    metabolic_snapshot: Optional[Dict[str, Any]] = None,
    vt1_w: Optional[float] = None,
    vt2_w: Optional[float] = None,
    vt1_bpm: Optional[float] = None,
    vt2_bpm: Optional[float] = None,
    hrv_window_seconds: int = 120,
    hrv_step_seconds: Optional[float] = None,
    hrv_max_windows: int = 500,
) -> Dict[str, Any]:
    """
    Produce the full per-activity report.

    Parameters
    ----------
    stream : ActivityStream-like
        From engines.fit_parser.parse_fit_file or parse_fit_records.
    weight_kg : float
        Athlete weight at time of activity.
    ftp : Optional[float]
        Functional Threshold Power. If None, will be estimated from the
        activity's MMP curve (20-min × 0.95 if available).
    lthr : Optional[float]
        Lactate Threshold Heart Rate. If None, Friel HR zones are skipped.
    context : Optional[AthleteContext]
        Used by HRV / cardiac engines for context-aware thresholds.
    metabolic_snapshot : Optional[dict]
        Output of MetabolicProfiler.generate_metabolic_snapshot() for cross-
        validation. If provided, cardiac engine reports HR @ MLSS, etc.
    vt1_w, vt2_w : Optional[float]
        Power thresholds for Seiler polarization (from prior testing).
    vt1_bpm, vt2_bpm : Optional[float]
        HR thresholds for Seiler polarization (fallback if no power thresholds).

    Returns
    -------
    dict with keys: status, schema_version, sections (power, zones,
    classification, hrv, cardiac, cross_validation), and headline (the
    six metrics a coach reviews daily).
    """
    if context is None:
        context = AthleteContext()

    _start_time = getattr(stream, "start_time", None)
    out: Dict[str, Any] = {
        "status": "success",
        "schema_version": "1.0.0",
        "stream_metadata": {
            "sport":         getattr(stream, "sport", "unknown"),
            "sub_sport":     getattr(stream, "sub_sport", None),
            "start_time":    _start_time.isoformat() if _start_time else None,
            "duration_s":    int(getattr(stream, "total_elapsed_s", 0) or 0),
            "distance_m":    getattr(stream, "total_distance_m", None),
            "ascent_m":      getattr(stream, "total_ascent_m", None),
            "device":        getattr(stream, "device_name", None),
            "n_samples":     getattr(stream, "n_samples", 0),
            "has_power":     getattr(stream, "has_power", False),
            "has_hr":        getattr(stream, "has_heart_rate", False),
            "has_rr":        getattr(stream, "has_rr", False),
        },
        "sections": {},
        "warnings": [],
    }
    annotate_payload(
        out,
        module_name="workout_summary",
        method="per_activity_orchestration",
        confidence=None,
    )

    # =========================================================================
    # 1. POWER METRICS (requires power)
    # =========================================================================
    power_result = None
    ftp_used = ftp
    ftp_source = "explicit" if ftp else None

    if not getattr(stream, "has_power", False):
        out["sections"]["power"] = {
            "available": False,
            "reason": "NO_POWER_DATA",
        }
    else:
        # If FTP not provided, we need to estimate it for TSS/IF/VI
        # Run a preliminary power analysis with a placeholder FTP=200 just
        # to get the MMP, then re-run with the estimated FTP.
        if ftp_used is None:
            tmp_engine = PowerEngine(ftp=200.0, weight_kg=weight_kg, ftp_source="placeholder")
            tmp_result = tmp_engine.analyze(stream)
            if tmp_result.get("status") == "success":
                est = estimate_ftp_from_mmp(tmp_result["mmp_curve"])
                if est.get("ftp_w"):
                    ftp_used = est["ftp_w"]
                    ftp_source = f"estimated:{est['method']}"
                    out["warnings"].append(
                        f"FTP not provided. Estimated as {ftp_used}W via {est['method']}. "
                        "TSS/IF/VI may be inaccurate vs a formal ramp test."
                    )

        if ftp_used is None:
            out["sections"]["power"] = {
                "available": False,
                "reason": "FTP_NOT_PROVIDED_AND_NOT_ESTIMABLE",
            }
        else:
            engine = PowerEngine(
                ftp=ftp_used,
                weight_kg=weight_kg,
                ftp_source=ftp_source or "explicit",
            )
            power_result = engine.analyze(stream)
            out["sections"]["power"] = power_result

    effective_cadence_rpm = derive_effective_cadence_rpm(stream)
    if metabolic_snapshot is None and power_result and power_result.get("status") == "success":
        mmp_dict = _mmp_curve_to_dict(power_result.get("mmp_curve") or [])
        if mmp_dict:
            profiler = MetabolicProfiler(weight=weight_kg, context=context)
            metabolic_snapshot = profiler.generate_metabolic_snapshot(
                mmp_dict,
                effective_cadence_rpm=effective_cadence_rpm,
                cadence_anchor_status="measured" if effective_cadence_rpm else "unknown",
            )
            if metabolic_snapshot.get("status") == "success":
                out["sections"]["metabolic_snapshot"] = metabolic_snapshot
    elif metabolic_snapshot and effective_cadence_rpm is not None:
        metabolic_snapshot = enrich_metabolic_snapshot_cadence(
            metabolic_snapshot,
            effective_cadence_rpm=effective_cadence_rpm,
        )
        if metabolic_snapshot.get("status") == "success":
            out["sections"]["metabolic_snapshot"] = metabolic_snapshot

    if metabolic_snapshot and metabolic_snapshot.get("status") == "success":
        out["cadence_anchor"] = metabolic_snapshot.get("cadence_anchor") or cadence_anchor_metadata(
            effective_cadence_rpm=effective_cadence_rpm,
            cadence_anchor_status="measured" if effective_cadence_rpm else "unknown",
        )
    elif effective_cadence_rpm is not None:
        out["cadence_anchor"] = cadence_anchor_metadata(
            effective_cadence_rpm=effective_cadence_rpm,
            cadence_anchor_status="measured",
        )

    if metabolic_snapshot and metabolic_snapshot.get("status") == "success":
        fatmax_report = build_model_fatmax_report(
            metabolic_snapshot,
            athlete_weight_kg=weight_kg,
            gender=context.effective_gender(),
            training_years=context.effective_training_years(),
            discipline=context.effective_discipline(),
        )
        out["sections"]["fatmax"] = fatmax_report

    # =========================================================================
    # 2. ZONES (metabolic MLSS + Coggan power + Friel HR + Seiler polarization)
    # =========================================================================
    zones_engine = ZonesEngine(ftp=ftp_used, lthr=lthr)
    out["sections"]["zones"] = zones_engine.analyze(
        stream,
        metabolic_snapshot=metabolic_snapshot if metabolic_snapshot and metabolic_snapshot.get("status") == "success" else None,
        vt1_w=vt1_w, vt2_w=vt2_w,
        vt1_bpm=vt1_bpm, vt2_bpm=vt2_bpm,
    )

    # =========================================================================
    # 3. COGGAN PHENOTYPE CLASSIFICATION (from MMP)
    # =========================================================================
    if power_result and power_result.get("status") == "success":
        out["sections"]["classification"] = classify_from_mmp(
            mmp_curve=power_result["mmp_curve"],
            weight_kg=weight_kg,
            gender=context.effective_gender(),
            ftp=ftp_used,
        )
    else:
        out["sections"]["classification"] = {
            "available": False,
            "reason": "NO_POWER_DATA_FOR_CLASSIFICATION",
        }

    # =========================================================================
    # 4. HRV / DFA-α₁ ANALYSIS (requires RR data)
    # =========================================================================
    hrv_timeline = None
    if getattr(stream, "has_rr", False):
        # Convert ActivityStream RR format to the format hrv_engine expects:
        # list of {"elapsed": t, "rr": [rr_ms_list]}
        rr_samples = [
            {"elapsed": float(stream.elapsed_s[i]), "rr": stream.rr_intervals[i]}
            for i in range(stream.n_samples)
            if stream.rr_intervals[i]
        ]
        if rr_samples:
            try:
                from engines.recovery.hrv_engine import analyze_rr_stream  # lazy — avoids circular import

                duration_s = float(getattr(stream, "total_elapsed_s", 0) or getattr(stream, "n_samples", 0) or 0)
                base_step = 10.0 if hrv_step_seconds is None else max(1.0, float(hrv_step_seconds))
                adaptive_step = base_step
                expected_windows = 0
                if duration_s > float(hrv_window_seconds):
                    expected_windows = int(max(0.0, duration_s - float(hrv_window_seconds)) / base_step) + 1
                if hrv_step_seconds is None and hrv_max_windows and expected_windows > hrv_max_windows:
                    adaptive_step = max(
                        base_step,
                        (duration_s - float(hrv_window_seconds)) / max(float(hrv_max_windows - 1), 1.0),
                    )
                    out["warnings"].append(
                        "HRV/DFA-alpha1 step increased from "
                        f"{base_step:.0f}s to {adaptive_step:.0f}s for a long activity "
                        f"({expected_windows} raw windows) to keep /ride/summary bounded."
                    )

                hrv_timeline = analyze_rr_stream(
                    rr_samples,
                    window_seconds=hrv_window_seconds,
                    step_seconds=adaptive_step,
                    context=context,
                )
                dfa_tier = tier_for("hrv_engine")
                out["sections"]["hrv"] = {
                    "available": True,
                    "n_windows": len(hrv_timeline),
                    "timeline": hrv_timeline,
                    "window_seconds": hrv_window_seconds,
                    "step_seconds": round(float(adaptive_step), 3),
                    "adaptive_step_applied": bool(abs(float(adaptive_step) - float(base_step)) > 1e-9),
                    "method": "dfa_alpha1",
                    "tier": dfa_tier.value,
                    "tier_explanation": dfa_tier.explanation,
                }
            except Exception as exc:
                out["sections"]["hrv"] = {
                    "available": False,
                    "reason": f"HRV_ANALYSIS_FAILED: {exc}",
                }
        else:
            out["sections"]["hrv"] = {
                "available": False,
                "reason": "RR_INTERVALS_EMPTY",
            }
    else:
        out["sections"]["hrv"] = {
            "available": False,
            "reason": "NO_RR_DATA_IN_STREAM",
        }

    # =========================================================================
    # 5. CARDIAC RESPONSE (drift, decoupling, recovery, kinetics, CEI, ...)
    # =========================================================================
    if getattr(stream, "has_heart_rate", False) and getattr(stream, "has_power", False):
        # Convert stream to ActivitySample list for cardiac_engine
        samples = []
        for i in range(stream.n_samples):
            p = stream.power[i]
            h = stream.heart_rate[i]
            if p is None or h is None:
                continue
            samples.append(ActivitySample(
                t=float(stream.elapsed_s[i]),
                power=float(p),
                hr=float(h),
            ))
        if samples:
            cardiac = CardiacResponseAnalyzer(
                weight=weight_kg,
                context=context,
                metabolic_snapshot=metabolic_snapshot,
                hrv_timeline=hrv_timeline,
            )
            out["sections"]["cardiac"] = cardiac.analyze(samples)
        else:
            out["sections"]["cardiac"] = {
                "available": False,
                "reason": "NO_VALID_SAMPLES_AFTER_FILTERING",
            }
    else:
        out["sections"]["cardiac"] = {
            "available": False,
            "reason": "MISSING_POWER_OR_HR",
        }

    # =========================================================================
    # 6. MADER DURABILITY — mechanistic residual CP (requires metabolic profile)
    # =========================================================================
    if (
        metabolic_snapshot
        and metabolic_snapshot.get("status") == "success"
        and getattr(stream, "has_power", False)
    ):
        try:
            from engines.performance.mader_durability import compute_session_durability
            power_list = [
                float(p or 0.0)
                for p in stream.power[: getattr(stream, "n_samples", len(stream.power))]
            ]
            md = compute_session_durability(power_list, metabolic_snapshot, weight_kg)
            out["sections"]["mader_durability"] = md
            if md.get("status") == "success":
                sus = md.get("sustainability") or {}
                headline_preview = (sus.get("sustainable_steady_power_w") or {}).get("at_10pct_cp_loss")
                if headline_preview:
                    out["warnings"].append(
                        "Mader durability: sustainable powers estimated from metabolic profile "
                        f"(session CP loss {md.get('durability_loss_pct', '?')}%)."
                    )
        except Exception as exc:
            out["sections"]["mader_durability"] = {
                "status": "error",
                "reason": str(exc),
            }
    elif metabolic_snapshot is None:
        out["sections"]["mader_durability"] = {
            "status": "skipped",
            "reason": "NO_METABOLIC_PROFILE",
            "message": (
                "Mader mechanistic durability requires generate_metabolic_snapshot() "
                "(sprint + CP 3/6/12 anchors or in-person testing)."
            ),
        }

    # =========================================================================
    # 7. BASIC STATISTICS PAGE (coach headline metrics)
    # =========================================================================
    stats = compute_activity_statistics(
        stream,
        weight_kg=weight_kg,
        ftp=ftp_used,
        cp=(
            (power_result.get("critical_power") or {}).get("cp_w")
            if power_result and power_result.get("status") == "success"
            else None
        ),
        lthr=lthr,
    )
    out["sections"]["statistics"] = stats
    out["statistics_page"] = stats.get("metrics", {})

    # =========================================================================
    # HEADLINE — the six metrics the coach checks daily
    # =========================================================================
    headline: Dict[str, Any] = {}

    if power_result and power_result.get("status") == "success":
        m = power_result["metrics"]
        headline["ftp_w"] = ftp_used
        headline["tss"] = m["tss"]
        headline["intensity_factor"] = m["intensity_factor"]
        headline["normalized_power"] = m["normalized_power"]
        headline["wkg_average"] = m["wkg_average"]
        headline["work_kj"] = m["work_kj"]
        headline["wkg_5s"] = m.get("wkg_5s")
        headline["wkg_5min"] = m.get("wkg_5min")
        headline["wkg_20min"] = m.get("wkg_20min")

    cardiac_section = out["sections"].get("cardiac", {})
    if cardiac_section.get("status") == "success":
        cs = cardiac_section.get("summary", {})
        headline["cardiac_fitness_class"] = cs.get("fitness_class")
        headline["cardiac_confidence"] = cs.get("confidence")
        # Pull the worst drift from any steady segment (most informative)
        drifts = [
            d.get("drift_pct") for d in cardiac_section.get("metrics", {}).get("cardiac_drift", [])
            if d.get("available")
        ]
        if drifts:
            headline["worst_cardiac_drift_pct"] = max(drifts)
        # Pull the worst decoupling
        decoups = [
            d.get("decoupling_pct") for d in cardiac_section.get("metrics", {}).get("aerobic_decoupling", [])
            if d.get("available")
        ]
        if decoups:
            headline["worst_aerobic_decoupling_pct"] = max(decoups)

    polarization = out["sections"].get("zones", {}).get("seiler_polarization", {})
    if polarization.get("available"):
        headline["session_distribution"] = polarization.get("distribution_class")

    classification = out["sections"].get("classification", {})
    if classification.get("status") == "success":
        headline["rider_phenotype"] = classification["overall"]["phenotype_code"]

    mader_section = out["sections"].get("mader_durability", {})
    if mader_section.get("status") == "success":
        headline["mader_durability_loss_pct"] = mader_section.get("durability_loss_pct")
        headline["mader_cp_baseline_w"] = mader_section.get("cp_baseline")
        sus = mader_section.get("sustainability") or {}
        at_10 = (sus.get("sustainable_steady_power_w") or {}).get("at_10pct_cp_loss") or {}
        if at_10.get("3h"):
            headline["mader_sustainable_3h_w"] = at_10["3h"]

    fatmax_section = out["sections"].get("fatmax") or {}
    if fatmax_section.get("status") == "success":
        fatmax_summary = fatmax_section.get("summary") or {}
        headline["fatmax_power_w"] = fatmax_summary.get("fatmax_power_w")
        headline["mfo_g_min"] = fatmax_summary.get("mfo_g_min")
        headline["fatmax_measurement_tier"] = fatmax_section.get("measurement_tier")

    out["physiological_resilience"] = build_physiological_resilience(
        mader_durability=mader_section if mader_section.get("status") == "success" else None,
        durability_index=out["sections"].get("durability"),
    )

    out["headline"] = headline

    # Schema normalization: guarantee every section carries a coherent `status`
    # field so consumers don't have to handle three conventions (`status`,
    # `available`, bare presence). A section that signalled unavailability via
    # `available: False` is mapped to status "unavailable"; everything else that
    # already has a status keeps it. This is additive — existing keys are
    # preserved, nothing is removed.
    for _name, _sec in out["sections"].items():
        if not isinstance(_sec, dict):
            continue
        if "status" not in _sec:
            if _sec.get("available") is False:
                _sec["status"] = "unavailable"
            elif _sec.get("available") is True:
                _sec["status"] = "success"
            else:
                _sec["status"] = "unknown"

    out["section_contracts"] = summarize_section_contracts(out["sections"])

    return out
