"""
Lactate validation engine — ground-truth thresholds vs Mader model (MMP)
========================================================================

Used by ``test_protocols.run_mader_test`` for in-person lactate step tests.
Computes MLSS via D-max (and interpolated LT1/LT2 anchors), then compares
against the non-invasive metabolic profile from ``MetabolicProfiler``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from lab_data import LactatePoint
from metric_contracts import annotate_payload


_MIN_LACTATE_STEPS = 5
_DEFAULT_TOLERANCE_PCT = 8.0


def steps_from_payload(raw_steps: Sequence[Dict[str, Any]]) -> List[LactatePoint]:
    """Normalize tablet/JSON step rows into ``LactatePoint`` list sorted by power."""
    points: List[LactatePoint] = []
    for row in raw_steps:
        if row.get("lactate_mmol") is None:
            continue
        try:
            lactate = float(row["lactate_mmol"])
        except (TypeError, ValueError):
            continue
        power = row.get("power_w")
        hr = row.get("hr_mean") or row.get("heart_rate_bpm")
        duration = row.get("duration_s")
        points.append(
            LactatePoint(
                power_w=float(power) if power is not None else None,
                heart_rate_bpm=float(hr) if hr is not None else None,
                lactate_mmol=lactate,
                duration_s=int(duration) if duration is not None else None,
            )
        )
    return sorted(points, key=lambda p: (p.power_w is None, p.power_w or 0.0))


def _coerce_mmp_dict(mmp: Union[Dict[Any, Any], List[Dict[str, Any]]]) -> Dict[int, float]:
    if isinstance(mmp, list):
        out: Dict[int, float] = {}
        for row in mmp:
            if not row:
                continue
            d = int(row["duration_s"])
            out[d] = float(row["power_w"])
        return out
    return {int(k): float(v) for k, v in mmp.items() if v is not None and float(v) > 0}


def _point_line_distance(
    x: float, y: float,
    x0: float, y0: float,
    x1: float, y1: float,
) -> float:
    """Perpendicular distance from (x,y) to the segment (x0,y0)-(x1,y1)."""
    dx, dy = x1 - x0, y1 - y0
    denom = np.hypot(dx, dy)
    if denom < 1e-9:
        return float(np.hypot(x - x0, y - y0))
    return float(abs(dy * x - dx * y + x1 * y0 - y1 * x0) / denom)


def _interpolate_power_at_lactate(
    powers: np.ndarray,
    lactates: np.ndarray,
    target_mmol: float,
) -> Optional[float]:
    """Linear interpolation of power at a target blood lactate level."""
    for i in range(len(lactates) - 1):
        la, lb = float(lactates[i]), float(lactates[i + 1])
        if la == lb:
            continue
        if (la <= target_mmol <= lb) or (lb <= target_mmol <= la):
            pa, pb = float(powers[i]), float(powers[i + 1])
            t = (target_mmol - la) / (lb - la)
            return pa + t * (pb - pa)
    return None


def compute_lactate_thresholds(
    steps: Sequence[LactatePoint],
) -> Dict[str, Any]:
    """
    D-max MLSS and common lactate anchors (2 / 4 mmol·L⁻¹).
    """
    valid = [s for s in steps if s.power_w is not None and s.lactate_mmol > 0]
    if len(valid) < _MIN_LACTATE_STEPS:
        return {
            "status": "error",
            "reason": "insufficient_steps",
            "message": f"Servono almeno {_MIN_LACTATE_STEPS} step con lattato e potenza.",
            "steps_provided": len(valid),
        }

    powers = np.array([float(s.power_w) for s in valid], dtype=float)
    lactates = np.array([float(s.lactate_mmol) for s in valid], dtype=float)

    # D-max: max distance from line first → last point (classic protocol).
    p0, l0 = float(powers[0]), float(lactates[0])
    pn, ln = float(powers[-1]), float(lactates[-1])
    max_dist = -1.0
    dmax_power = float(powers[0])
    for i in range(1, len(powers) - 1):
        d = _point_line_distance(float(powers[i]), float(lactates[i]), p0, l0, pn, ln)
        if d > max_dist:
            max_dist = d
            dmax_power = float(powers[i])

    aerobic_2 = _interpolate_power_at_lactate(powers, lactates, 2.0)
    obla_4 = _interpolate_power_at_lactate(powers, lactates, 4.0)

    return {
        "status": "success",
        "mlss_dmax_watts": round(dmax_power, 1),
        "aerobic_2mmol_watts": round(aerobic_2, 1) if aerobic_2 is not None else None,
        "obla_4mmol_watts": round(obla_4, 1) if obla_4 is not None else None,
        "n_steps": len(valid),
    }


def validate_model_against_lactate(
    steps: Sequence[LactatePoint],
    profiler,
    mmp: Union[Dict[Any, Any], List[Dict[str, Any]]],
    expected_eta: Optional[float] = None,
    tolerance_pct: float = _DEFAULT_TOLERANCE_PCT,
) -> Dict[str, Any]:
    """
    Compare lactate-derived MLSS (D-max) with Mader model MLSS from MMP.
    """
    thresholds = compute_lactate_thresholds(steps)
    if thresholds.get("status") != "success":
        return annotate_payload(
            thresholds,
            module_name="lactate_validation_engine",
            method="validate_model_against_lactate",
            confidence=0.0,
        )

    mmp_dict = _coerce_mmp_dict(mmp)
    if len(mmp_dict) < 3:
        return annotate_payload(
            {
                "status": "error",
                "reason": "insufficient_mmp",
                "message": "MMP insufficiente per il profilo metabolico (min 3 durate).",
            },
            module_name="lactate_validation_engine",
            method="validate_model_against_lactate",
            confidence=0.0,
        )

    snapshot = profiler.generate_metabolic_snapshot(mmp_dict, expected_eta=expected_eta)
    if snapshot.get("status") != "success":
        return annotate_payload(
            {
                "status": "error",
                "reason": "metabolic_profile_failed",
                "message": snapshot.get("message", "Profilo metabolico non disponibile."),
            },
            module_name="lactate_validation_engine",
            method="validate_model_against_lactate",
            confidence=0.0,
        )

    unmasked = snapshot.get("unmasked_estimates") or {}
    mlss_model = unmasked.get("mlss_power_watts") or snapshot.get("mlss_power_watts")
    if mlss_model is None:
        return annotate_payload(
            {
                "status": "error",
                "reason": "mlss_masked",
                "message": "MLSS del modello non disponibile (expressiveness gate).",
                "model_snapshot": snapshot,
            },
            module_name="lactate_validation_engine",
            method="validate_model_against_lactate",
            confidence=0.0,
        )

    mlss_true = float(thresholds["mlss_dmax_watts"])
    mlss_model_f = float(mlss_model)
    error_w = mlss_model_f - mlss_true
    error_pct = (error_w / mlss_true) * 100.0 if mlss_true > 0 else 0.0
    validated = abs(error_pct) <= tolerance_pct

    if validated:
        verdict = (
            f"Modello VALIDATO per questo atleta: MLSS lattato (D-max) {mlss_true:.0f}W, "
            f"MLSS modello {mlss_model_f:.0f}W (scarto {error_pct:+.1f}%)."
        )
        confidence = 0.9
    else:
        verdict = (
            f"Modello NON validato: MLSS lattato {mlss_true:.0f}W vs modello "
            f"{mlss_model_f:.0f}W (scarto {error_pct:+.1f}%, soglia ±{tolerance_pct:.0f}%). "
            "Rivedere MMP o ripetere il test."
        )
        confidence = 0.5

    payload = {
        "status": "success",
        "validated": validated,
        "verdict": verdict,
        "mlss_true_watts": round(mlss_true, 1),
        "mlss_model_watts": round(mlss_model_f, 1),
        "error_watts": round(error_w, 1),
        "error_pct": round(error_pct, 1),
        "tolerance_pct": tolerance_pct,
        "lactate_thresholds": {
            "mlss_dmax_watts": thresholds["mlss_dmax_watts"],
            "obla_4mmol_watts": thresholds.get("obla_4mmol_watts"),
            "aerobic_2mmol_watts": thresholds.get("aerobic_2mmol_watts"),
        },
        "model_snapshot": snapshot,
    }
    return annotate_payload(
        payload,
        module_name="lactate_validation_engine",
        method="validate_model_against_lactate",
        confidence=confidence,
        limitations=[
            "D-max MLSS depends on step protocol quality and lactate sampling.",
            "Model MLSS is Mader-derived from MMP, not direct measurement.",
        ],
    )
