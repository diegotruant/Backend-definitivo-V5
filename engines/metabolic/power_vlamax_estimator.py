"""
Power-series VLamax proxy (cLaMax_P) — glycolytic rate estimate from sprint power.

Literature-informed features: fixed T_PCr 3.5 s (Meixner 2024 / Dunst 2023),
t_Ppeak retained as protocol-quality metadata only, FFM-normalized work,
relative sprint power, and sprint-vs-endurance distinction.

Semantics: this is a **power-derived proxy**, not direct blood lactate measurement.
Distinct from Mader model VLamax (vLamax_muscle) and from observed vLaPeak.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from engines.core.metric_contracts import annotate_payload

J_PER_MMOL_LACTATE_PER_KG = 63.0
_VLAMAX_CLIP_LO = 0.05
_VLAMAX_CLIP_HI = 1.50


def _min_sustain_ratio(duration_s: float) -> float:
    """Match metabolic_profiler.vlamax_from_sprint sustain gate."""
    return max(0.40, 0.70 - 0.012 * duration_s)


def estimate_vlamax_from_power_series(
    power: List[float],
    *,
    dt_s: float = 1.0,
    weight_kg: float,
    eta: float,
    active_muscle_mass_kg: float,
    vo2max_power_w: Optional[float] = None,
    cp_w: Optional[float] = None,
    oxi_fraction: Optional[float] = None,
    lactate_pre_mmol_l: Optional[float] = None,
    lactate_peak_mmol_l: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Estimate VLamax proxy from a maximal sprint power trace (8–30 s, 1 Hz typical).

    Decomposes mean sprint power into alactic + aerobic + glycolytic components,
    then converts glycolytic power to mmol·L⁻¹·s⁻¹ over active muscle mass.
    """
    if active_muscle_mass_kg <= 0 or weight_kg <= 0:
        return {"status": "error", "reason": "invalid_mass", "message": "Mass must be positive."}
    if eta <= 0:
        return {"status": "error", "reason": "invalid_eta", "message": "Mechanical efficiency must be positive."}

    try:
        p = np.asarray(power, dtype=float)
    except (TypeError, ValueError):
        return {"status": "error", "reason": "invalid_power", "message": "Power must be numeric."}

    if p.size < 8:
        return {
            "status": "error",
            "reason": "power_too_short",
            "message": "At least 8 power samples required.",
        }

    dt = float(dt_s)
    if dt <= 0 or dt > 1.0:
        return {"status": "error", "reason": "invalid_dt", "message": "dt_s must be in (0, 1]."}

    duration_s = float(p.size * dt)
    if duration_s < 8.0 or duration_s > 30.0:
        return {
            "status": "invalid_protocol",
            "reason": "duration_outside_8_30s",
            "duration_s": round(duration_s, 2),
        }

    p_peak = float(np.max(p))
    if p_peak <= 0:
        return {"status": "error", "reason": "non_positive_power", "message": "Peak power must be positive."}

    from engines.performance.sprint_peak_analysis import analyze_sprint_power

    peak_analysis = analyze_sprint_power(p, dt_s=dt)
    p_neuro = peak_analysis.neuromuscular_peak_w if peak_analysis else p_peak
    i_peak = int(np.argmax(p))
    t_p_peak = peak_analysis.t_p_peak_s if peak_analysis else i_peak * dt
    p_mean = float(np.mean(p))

    end_n = max(1, int(round(1.0 / dt)))
    p_end = float(np.mean(p[max(0, p.size - end_n) :]))
    fatigue_index = (p_peak - p_end) / max(p_peak, 1e-9)
    sustain_ratio = p_mean / p_neuro

    min_sustain = _min_sustain_ratio(duration_s)
    if sustain_ratio < min_sustain:
        return {
            "status": "insufficient_sprint",
            "message": (
                f"Sprint not maximal/sustained enough (mean/peak={sustain_ratio:.2f}, "
                f"need >= {min_sustain:.2f})."
            ),
            "sustain_ratio": round(sustain_ratio, 3),
            "features": {
                "p_peak_w": round(p_peak, 1),
                "p_mean_w": round(p_mean, 1),
                "duration_s": round(duration_s, 2),
            },
        }

    # T_PCR: fixed alactic phase duration per Meixner 2024 / Dunst 2023.
    # Using t_Ppeak as t_PCr is unreliable (ICC 0.79 vs 0.91 for fixed 3.5 s)
    # and introduces systematic bias when peak is reached late (amateur
    # athletes, trainer inertia, suboptimal pacing). Glycolytic flux rises
    # significantly after ~3-4 s regardless of mechanical peak timing.
    # t_p_peak is retained as a protocol quality indicator only.
    T_PCR_S = 3.5  # s, fixed (Meixner 2024)

    w_total_j = float(np.sum(p) * dt)
    # Glycolytic work window starts at T_PCR_S, not at t_p_peak
    i_pcr = min(int(round(T_PCR_S / dt)), p.size - 1)
    w_lac_j = float(np.sum(p[i_pcr:]) * dt)
    t_lac_s = max(duration_s - T_PCR_S, 1e-9)
    p_mean_lac = w_lac_j / t_lac_s

    if oxi_fraction is None:
        oxi_fraction = 0.03 if duration_s >= 14.0 else 0.02

    t_oxi = duration_s * float(oxi_fraction)
    t_gly = max(duration_s - T_PCR_S - t_oxi, 1.0)

    # Alactic contribution: mean power in [0, T_PCR_S] window
    early_n = max(1, min(int(round(T_PCR_S / dt)), p.size))
    p_early_mean = float(np.mean(p[:early_n]))
    if peak_analysis and peak_analysis.recruitment_profile == "delayed":
        p_alac_avg = min(p_neuro, p_peak) * (T_PCR_S / duration_s)
    else:
        p_alac_avg = min(p_early_mean, p_neuro) * (T_PCR_S / duration_s)

    aero_ceiling = vo2max_power_w if vo2max_power_w is not None else cp_w
    if aero_ceiling is not None and float(aero_ceiling) > 0:
        p_aero_avg = float(aero_ceiling) * float(oxi_fraction)
    else:
        p_aero_avg = 0.0

    p_glyc_avg = max(0.0, p_mean - p_alac_avg - p_aero_avg)
    glyc_metabolic_rate = p_glyc_avg / eta
    vlamax_raw = glyc_metabolic_rate / (J_PER_MMOL_LACTATE_PER_KG * active_muscle_mass_kg)

    if vlamax_raw < 0.08:
        return {
            "status": "insufficient_sprint",
            "message": "Glycolytic component resolved to ~0; cannot estimate VLamax proxy.",
            "features": {
                "p_glyc_avg_w": round(p_glyc_avg, 1),
                "p_alac_avg_w": round(p_alac_avg, 1),
                "p_aero_avg_w": round(p_aero_avg, 1),
            },
        }

    vlamax = float(np.clip(vlamax_raw, _VLAMAX_CLIP_LO, _VLAMAX_CLIP_HI))

    quality_flags: List[str] = []
    if sustain_ratio < min_sustain + 0.05:
        quality_flags.append("borderline_sustain_ratio")
    if peak_analysis and peak_analysis.recruitment_profile == "delayed":
        quality_flags.append("delayed_motor_recruitment")
    # t_p_peak > 3.5 s: mechanical peak after alactic phase — protocol note only.
    if t_p_peak > 6.0:
        quality_flags.append("very_late_power_peak_protocol_note")
    elif t_p_peak > 3.5:
        quality_flags.append("late_power_peak_protocol_note")
    if fatigue_index < 0.10:
        quality_flags.append("weak_fatigue_signature")
    if vo2max_power_w is None and cp_w is None:
        quality_flags.append("no_aerobic_anchor")

    # late_power_peak flags are protocol notes, not physiological errors —
    # don't penalize confidence for them since T_PCR_S is fixed regardless.
    confidence_penalty_flags = [
        f for f in quality_flags
        if f not in ("late_power_peak_protocol_note", "very_late_power_peak_protocol_note")
    ]
    confidence = 0.85 - 0.12 * len(confidence_penalty_flags)
    if vo2max_power_w is None and cp_w is None:
        confidence -= 0.10
    if "very_late_power_peak_protocol_note" in quality_flags:
        confidence -= 0.05  # mild penalty only for very late peak (>6 s)
    confidence = float(np.clip(confidence, 0.05, 0.95))

    features: Dict[str, Any] = {
        "duration_s": round(duration_s, 2),
        "t_pcr_s": T_PCR_S,
        "t_p_peak_s": round(t_p_peak, 2),
        "p_peak_w": round(p_peak, 1),
        "p_mean_w": round(p_mean, 1),
        "neuromuscular_peak_w": round(p_neuro, 1),
        "p_peak_wkg": round(p_peak / weight_kg, 2),
        "p_mean_wkg": round(p_mean / weight_kg, 2),
        "t_oxi_s": round(t_oxi, 2),
        "t_gly_s": round(t_gly, 2),
        "w_total_j": round(w_total_j, 1),
        "w_lac_j": round(w_lac_j, 1),
        "w_lac_j_per_kg": round(w_lac_j / weight_kg, 1),
        "w_total_j_per_ffm": round(w_total_j / active_muscle_mass_kg, 1),
        "w_lac_j_per_ffm": round(w_lac_j / active_muscle_mass_kg, 1),
        "p_mean_lac_w": round(p_mean_lac, 1),
        "p_glyc_avg_w": round(p_glyc_avg, 1),
        "fatigue_index": round(fatigue_index, 3),
        "sustain_ratio": round(sustain_ratio, 3),
        "oxi_fraction": round(float(oxi_fraction), 4),
    }

    out: Dict[str, Any] = {
        "status": "success",
        "estimated_vlamax_mmol_l_s": round(vlamax, 4),
        "vlamax_mmol_l_s": round(vlamax, 4),
        "method": "power_series_glycolytic_proxy_v1",
        "confidence": round(confidence, 3),
        "features": features,
        "quality_flags": quality_flags,
        "semantics": "power-derived VLamax proxy; not direct blood lactate measurement",
        "sprint_peak_contract": peak_analysis.to_dict() if peak_analysis else None,
        "inputs": {
            "weight_kg": weight_kg,
            "active_muscle_mass_kg": round(active_muscle_mass_kg, 2),
            "eta": round(float(eta), 4),
            "vo2max_power_w": round(float(vo2max_power_w), 1) if vo2max_power_w else None,
            "cp_w": round(float(cp_w), 1) if cp_w else None,
            "n_samples": int(p.size),
            "dt_s": dt,
        },
    }

    if lactate_pre_mmol_l is not None and lactate_peak_mmol_l is not None:
        delta_la = float(lactate_peak_mmol_l) - float(lactate_pre_mmol_l)
        if delta_la > 0 and t_gly > 0:
            observed_vlapeak = delta_la / t_gly
            out["observed_vlapeak_mmol_l_s"] = round(observed_vlapeak, 4)
            out["lactate_calibration"] = {
                "lactate_pre_mmol_l": round(float(lactate_pre_mmol_l), 2),
                "lactate_peak_mmol_l": round(float(lactate_peak_mmol_l), 2),
                "lactate_delta_mmol_l": round(delta_la, 2),
                "t_gly_s": round(t_gly, 2),
                "delta_vs_power_proxy_pct": round(
                    100.0 * (observed_vlapeak - vlamax) / max(vlamax, 1e-9), 1
                ),
            }

    return annotate_payload(
        out,
        module_name="power_vlamax_estimator",
        method="power_series_glycolytic_proxy_v1",
        confidence=confidence,
    )
