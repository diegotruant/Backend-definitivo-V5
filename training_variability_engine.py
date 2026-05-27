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


def calculate_acwr(atl: float, ctl: float) -> Dict[str, Any]:
    """ACWR = ATL / CTL"""
    if ctl == 0:
        return {"status": "error", "error": "CTL is zero"}
    
    acwr = atl / ctl
    
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
    
    return {
        "acwr": round(acwr, 2),
        "risk_level": risk,
        "recommendation": rec,
    }


def calculate_monotony_strain(daily_tss: List[float]) -> Dict[str, Any]:
    """Monotony & Strain (Foster 1998)"""
    if len(daily_tss) < 7:
        return {"status": "insufficient_data"}
    
    mean_tss = np.mean(daily_tss)
    std_tss = np.std(daily_tss)
    
    monotony = mean_tss / std_tss if std_tss > 0 else 0
    weekly_tss = sum(daily_tss)
    strain = weekly_tss * monotony
    
    if monotony > 2.0:
        status = "HIGH_RISK"
        rec = "Add training variety — sessions too similar"
    elif monotony > 1.5:
        status = "MODERATE"
        rec = "Consider more variability"
    else:
        status = "OPTIMAL"
        rec = "Good training variety"
    
    return {
        "monotony": round(monotony, 2),
        "strain": round(strain, 0),
        "weekly_tss": round(weekly_tss, 0),
        "status": status,
        "recommendation": rec,
    }


if __name__ == "__main__":
    # Example
    acwr = calculate_acwr(atl=75.0, ctl=58.0)
    monotony = calculate_monotony_strain([80, 65, 90, 75, 100, 60, 85])
    
    print("ACWR:", acwr["acwr"], "→", acwr["risk_level"])
    print("Monotony:", monotony["monotony"], "→", monotony["status"])
    print("Strain:", monotony["strain"])
