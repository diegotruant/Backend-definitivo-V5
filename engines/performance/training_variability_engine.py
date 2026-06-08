"""
Training Variability Metrics — ACWR, Monotony, Strain
Version: 1.0.0

RESEARCH: Gabbett 2016, Foster 1998, Hulin 2016

METRICS:
1. ACWR (Acute:Chronic Workload Ratio) = ATL / CTL
   - Sweet spot: 0.8-1.3
   - >1.5 = injury risk
   - <0.8 = detraining
2. Monotony = Mean(daily TSS) / SD(daily TSS)
   - >2.0 = high risk
   - <1.5 = optimal variety
3. Strain = Weekly TSS × Monotony
"""

from typing import Dict, Any, List

import numpy as np

from engines.core.metric_contracts import annotate_payload

# Daily TSS standard deviation below this (TSS units) makes monotony unstable.
_MONOTONY_MIN_STD_TSS = 1.0
# CTL below this makes ACWR ratios hard to interpret.
_ACWR_LOW_CTL_THRESHOLD = 5.0


def calculate_acwr(atl: float, ctl: float) -> Dict[str, Any]:
    """ACWR = ATL / CTL with explicit edge-case flags."""
    if ctl == 0:
        return annotate_payload(
            {
                "status": "error",
                "error": "CTL is zero",
                "edge_case_flags": ["ctl_zero"],
            },
            module_name="training_variability_engine",
            method="acute_chronic_workload_ratio",
            confidence=0.0,
            limitations=["ACWR is undefined when chronic load (CTL) is zero."],
        )

    acwr = atl / ctl
    edge_case_flags: List[str] = []

    if ctl < _ACWR_LOW_CTL_THRESHOLD:
        edge_case_flags.append("low_chronic_load")
    if atl <= 0:
        edge_case_flags.append("zero_acute_load")

    if acwr > 1.5:
        risk = "HIGH"
        rec = "Reduce load — injury risk elevated"
    elif acwr > 1.3:
        risk = "MODERATE"
        rec = "Caution — approaching high load"
    elif acwr < 0.8:
        risk = "DETRAINING"
        rec = "Load too low — fitness declining"
    else:
        risk = "OPTIMAL"
        rec = "Good acute:chronic balance"

    confidence = 0.35 if edge_case_flags else 0.6
    limitations = [
        "ACWR risk zones are debated in sports-science literature; use as a guide only.",
    ]
    if "low_chronic_load" in edge_case_flags:
        limitations.append(
            f"CTL below {_ACWR_LOW_CTL_THRESHOLD:.0f} — ratio may be unstable or misleading."
        )

    return annotate_payload(
        {
            "status": "success",
            "acwr": round(acwr, 2),
            "risk_level": risk,
            "recommendation": rec,
            "atl": round(atl, 1),
            "ctl": round(ctl, 1),
            "edge_case_flags": edge_case_flags,
        },
        module_name="training_variability_engine",
        method="acute_chronic_workload_ratio",
        confidence=confidence,
        limitations=limitations,
    )


def calculate_monotony_strain(daily_tss: List[float]) -> Dict[str, Any]:
    """Monotony & Strain (Foster 1998) with near-zero variance handling."""
    if len(daily_tss) < 7:
        return annotate_payload(
            {"status": "insufficient_data", "days_available": len(daily_tss)},
            module_name="training_variability_engine",
            method="monotony_strain",
            confidence=0.0,
            limitations=["Requires at least 7 days of daily TSS."],
        )

    tss = np.asarray(daily_tss, dtype=float)
    mean_tss = float(np.mean(tss))
    std_tss = float(np.std(tss))
    weekly_tss = float(np.sum(tss))
    edge_case_flags: List[str] = []

    if std_tss < _MONOTONY_MIN_STD_TSS:
        edge_case_flags.append("near_zero_daily_tss_variance")
        monotony = None
        strain = None
        monotony_status = "UNSTABLE"
        rec = "Daily TSS too uniform — monotony/strain not meaningful"
        confidence = 0.2
    else:
        monotony = mean_tss / std_tss
        strain = weekly_tss * monotony
        if monotony > 2.0:
            monotony_status = "HIGH_RISK"
            rec = "Add training variety — sessions too similar"
        elif monotony > 1.5:
            monotony_status = "MODERATE"
            rec = "Consider more variability"
        else:
            monotony_status = "OPTIMAL"
            rec = "Good training variety"
        confidence = 0.55

    limitations = [
        "Monotony becomes unstable when daily TSS variance is very low.",
        "Foster monotony/strain are heuristic load-variability indicators.",
    ]

    payload: Dict[str, Any] = {
        "status": "success" if monotony is not None else "unstable",
        "weekly_tss": round(weekly_tss, 0),
        "mean_daily_tss": round(mean_tss, 1),
        "std_daily_tss": round(std_tss, 2),
        "monotony_status": monotony_status,
        "recommendation": rec,
        "edge_case_flags": edge_case_flags,
    }
    if monotony is not None:
        payload["monotony"] = round(monotony, 2)
        payload["strain"] = round(strain, 0)
    else:
        payload["monotony"] = None
        payload["strain"] = None

    return annotate_payload(
        payload,
        module_name="training_variability_engine",
        method="monotony_strain",
        confidence=confidence,
        limitations=limitations,
    )


if __name__ == "__main__":
    acwr = calculate_acwr(atl=75.0, ctl=58.0)
    monotony = calculate_monotony_strain([80, 65, 90, 75, 100, 60, 85])
    flat_week = calculate_monotony_strain([50.0] * 7)

    print("ACWR:", acwr["acwr"], "→", acwr["risk_level"], acwr.get("edge_case_flags"))
    print("Monotony:", monotony["monotony"], "→", monotony["monotony_status"])
    print("Strain:", monotony["strain"])
    print("Flat week:", flat_week["status"], flat_week.get("edge_case_flags"))
