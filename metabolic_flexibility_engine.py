"""
Metabolic Flexibility Engine
Version: 1.0.0

RESEARCH: San-Millán & Brooks 2018, Jeukendrup & Wallis 2005

METRICS:
1. Metabolic Flexibility Index (MFI) = FatMax_power / VT2_power
   - >0.70: Excellent fat adaptation
   - 0.60-0.70: Good
   - <0.60: Carb-dependent
2. Crossover Point = power where CHO > fat oxidation
3. Fat Oxidation Efficiency = g/min at FatMax
"""

from typing import Dict, Any


def calculate_metabolic_flexibility_index(
    fatmax_watts: float,
    vt2_watts: float,
) -> Dict[str, Any]:
    """
    MFI = FatMax / VT2
    
    Higher MFI = better fat utilization at intensity
    """
    if vt2_watts == 0:
        return {"status": "error"}
    
    mfi = fatmax_watts / vt2_watts
    
    if mfi >= 0.70:
        classification = "EXCELLENT"
        interpretation = "Elite fat adaptation — high metabolic flexibility"
    elif mfi >= 0.60:
        classification = "GOOD"
        interpretation = "Good fat utilization"
    else:
        classification = "CARB_DEPENDENT"
        interpretation = "Carbohydrate-dependent — improve aerobic base"
    
    return {
        "mfi": round(mfi, 2),
        "classification": classification,
        "interpretation": interpretation,
        "fatmax_watts": fatmax_watts,
        "vt2_watts": vt2_watts,
    }


def estimate_fat_oxidation_rate(
    fatmax_watts: float,
    weight_kg: float,
) -> Dict[str, Any]:
    """
    Estimate fat oxidation rate at FatMax.
    
    Research: Jeukendrup & Achten (2001)
    Trained cyclists: ~0.5-1.0 g/min
    Elite: >1.0 g/min
    """
    # Empirical formula (approximate)
    # Fat oxidation (g/min) ≈ 0.001 × FatMax_watts
    fat_ox_rate = fatmax_watts * 0.001
    
    if fat_ox_rate >= 1.0:
        classification = "ELITE"
    elif fat_ox_rate >= 0.7:
        classification = "TRAINED"
    else:
        classification = "RECREATIONAL"
    
    return {
        "fat_oxidation_g_per_min": round(fat_ox_rate, 2),
        "classification": classification,
    }


if __name__ == "__main__":
    mfi = calculate_metabolic_flexibility_index(fatmax_watts=215, vt2_watts=315)
    fat_ox = estimate_fat_oxidation_rate(fatmax_watts=215, weight_kg=75)
    
    print("Metabolic Flexibility Index:", mfi["mfi"], "→", mfi["classification"])
    print("Fat oxidation rate:", fat_ox["fat_oxidation_g_per_min"], "g/min →", fat_ox["classification"])
