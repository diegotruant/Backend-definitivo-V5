"""Sprint peak timing and recruitment-aware neuromuscular ceiling selection.

Amateur and some professional athletes may reach true peak power several
seconds into a maximal sprint (slow fibre recruitment / RFD), not within the
first 1–3 s assumed by classic Wingate/VLamax protocols.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

EARLY_PEAK_THRESHOLD_S = 3.0
DELAYED_RECRUITMENT_THRESHOLD_S = 3.0
LATE_PEAK_FLAG_THRESHOLD_S = 4.0


@dataclass(frozen=True)
class SprintPeakAnalysis:
    peak_1s_w: float
    peak_3s_w: float
    peak_5s_w: float
    t_p_peak_s: float
    neuromuscular_peak_w: float
    neuromuscular_peak_window_s: int
    recruitment_profile: str  # "early" | "delayed"
    recruitment_lag_s: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "peak_1s_w": round(self.peak_1s_w, 1),
            "peak_3s_w": round(self.peak_3s_w, 1),
            "peak_5s_w": round(self.peak_5s_w, 1),
            "t_p_peak_s": round(self.t_p_peak_s, 2),
            "neuromuscular_peak_w": round(self.neuromuscular_peak_w, 1),
            "neuromuscular_peak_window_s": self.neuromuscular_peak_window_s,
            "recruitment_profile": self.recruitment_profile,
            "recruitment_lag_s": round(self.recruitment_lag_s, 2),
        }


def _rolling_max_mean(power: np.ndarray, window_s: float, dt_s: float) -> float:
    w = max(1, int(round(window_s / dt_s)))
    if power.size < w:
        return float(np.max(power)) if power.size else 0.0
    cumsum = np.concatenate([[0.0], np.cumsum(power)])
    window_sums = cumsum[w:] - cumsum[:-w]
    if window_sums.size == 0:
        return 0.0
    return float(np.max(window_sums) / w)


def analyze_sprint_power(
    power: Sequence[float],
    *,
    dt_s: float = 1.0,
) -> Optional[SprintPeakAnalysis]:
    """Derive instantaneous and rolling sprint peaks plus recruitment profile."""
    if dt_s <= 0 or dt_s > 1.0:
        raise ValueError("dt_s must be in (0, 1]")
    try:
        p = np.asarray([float(x) for x in power if x is not None], dtype=float)
    except (TypeError, ValueError):
        return None
    p = p[np.isfinite(p) & (p >= 0)]
    if p.size < 3:
        return None

    i_peak = int(np.argmax(p))
    peak_1s = float(p[i_peak])
    if peak_1s <= 0:
        return None

    t_p_peak = float(i_peak * dt_s)
    peak_3s = _rolling_max_mean(p, 3.0, dt_s)
    peak_5s = _rolling_max_mean(p, 5.0, dt_s)

    if t_p_peak > DELAYED_RECRUITMENT_THRESHOLD_S:
        profile = "delayed"
        candidates = [(peak_1s, 1), (peak_3s, 3), (peak_5s, 5)]
        neuromuscular_peak_w, window_s = max(candidates, key=lambda item: item[0])
    else:
        profile = "early"
        neuromuscular_peak_w = peak_1s
        window_s = 1

    recruitment_lag = max(0.0, t_p_peak - EARLY_PEAK_THRESHOLD_S)

    return SprintPeakAnalysis(
        peak_1s_w=peak_1s,
        peak_3s_w=peak_3s,
        peak_5s_w=peak_5s,
        t_p_peak_s=t_p_peak,
        neuromuscular_peak_w=neuromuscular_peak_w,
        neuromuscular_peak_window_s=window_s,
        recruitment_profile=profile,
        recruitment_lag_s=recruitment_lag,
    )


def neuromuscular_peak_for_decomposition(
    *,
    p_peak_1s: float,
    p_mean_sprint: float,
    sprint_duration_s: float,
    t_p_peak_s: Optional[float] = None,
    peak_3s_w: Optional[float] = None,
    peak_5s_w: Optional[float] = None,
    neuromuscular_peak_w: Optional[float] = None,
    power: Optional[Sequence[float]] = None,
    dt_s: float = 1.0,
) -> Dict[str, Any]:
    """Resolve the power ceiling used for alactic decomposition and sustain gates."""
    analysis: Optional[SprintPeakAnalysis] = None
    if power is not None:
        analysis = analyze_sprint_power(power, dt_s=dt_s)

    if analysis is not None:
        contract = analysis.to_dict()
        ceiling = analysis.neuromuscular_peak_w
    else:
        contract = {
            "peak_1s_w": round(float(p_peak_1s), 1),
            "peak_3s_w": round(float(peak_3s_w), 1) if peak_3s_w is not None else None,
            "peak_5s_w": round(float(peak_5s_w), 1) if peak_5s_w is not None else None,
            "t_p_peak_s": round(float(t_p_peak_s), 2) if t_p_peak_s is not None else None,
        }
        if neuromuscular_peak_w is not None and neuromuscular_peak_w > 0:
            ceiling = float(neuromuscular_peak_w)
            contract["neuromuscular_peak_w"] = round(ceiling, 1)
            contract["neuromuscular_peak_window_s"] = 0
            contract["recruitment_profile"] = (
                "delayed" if (t_p_peak_s or 0) > DELAYED_RECRUITMENT_THRESHOLD_S else "early"
            )
        elif (
            t_p_peak_s is not None
            and t_p_peak_s > DELAYED_RECRUITMENT_THRESHOLD_S
            and (peak_3s_w is not None or peak_5s_w is not None)
        ):
            candidates = [(float(p_peak_1s), 1)]
            if peak_3s_w is not None:
                candidates.append((float(peak_3s_w), 3))
            if peak_5s_w is not None:
                candidates.append((float(peak_5s_w), 5))
            ceiling, window_s = max(candidates, key=lambda item: item[0])
            contract["neuromuscular_peak_w"] = round(ceiling, 1)
            contract["neuromuscular_peak_window_s"] = window_s
            contract["recruitment_profile"] = "delayed"
            contract["recruitment_lag_s"] = round(max(0.0, t_p_peak_s - EARLY_PEAK_THRESHOLD_S), 2)
        else:
            ceiling = float(p_peak_1s)
            contract["neuromuscular_peak_w"] = round(ceiling, 1)
            contract["neuromuscular_peak_window_s"] = 1
            contract["recruitment_profile"] = "early"
            contract["recruitment_lag_s"] = 0.0

    sustain_ratio = float(p_mean_sprint) / ceiling if ceiling > 0 else 0.0
    quality_flags: List[str] = []
    if contract.get("recruitment_profile") == "delayed":
        quality_flags.append("delayed_motor_recruitment")
    t_peak = contract.get("t_p_peak_s")
    if t_peak is not None and float(t_peak) > LATE_PEAK_FLAG_THRESHOLD_S:
        quality_flags.append("late_power_peak")

    return {
        "neuromuscular_peak_w": ceiling,
        "sprint_peak_contract": contract,
        "sustain_ratio": sustain_ratio,
        "quality_flags": quality_flags,
    }
