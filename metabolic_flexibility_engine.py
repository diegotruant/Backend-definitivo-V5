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
3. Fat Oxidation Efficiency = g/min at FatMax (absolute and per kg)
"""

from typing import Dict, Any

from metric_contracts import annotate_payload


def calculate_metabolic_flexibility_index(
    fatmax_watts: float,
    vt2_watts: float,
) -> Dict[str, Any]:
    """
    MFI = FatMax / VT2

    Higher MFI = better fat utilization at intensity
    """
    if vt2_watts == 0:
        return annotate_payload(
            {"status": "error", "reason": "vt2_watts_zero"},
            module_name="metabolic_flexibility_engine",
            method="metabolic_flexibility_index",
            confidence=0.0,
        )

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

    return annotate_payload(
        {
            "mfi": round(mfi, 2),
            "classification": classification,
            "interpretation": interpretation,
            "fatmax_watts": fatmax_watts,
            "vt2_watts": vt2_watts,
            "status": "success",
        },
        module_name="metabolic_flexibility_engine",
        method="metabolic_flexibility_index",
        confidence=0.55,
        limitations=["MFI thresholds are heuristic population guidelines."],
    )


def estimate_fat_oxidation_rate(
    fatmax_watts: float,
    weight_kg: float,
) -> Dict[str, Any]:
    """
    Estimate fat oxidation rate at FatMax.

    Research: Jeukendrup & Achten (2001)
    Trained cyclists: ~0.5-1.0 g/min absolute; mass-normalized bands use
    mg fat · kg⁻¹ · min⁻¹ for inter-athlete comparison.
    """
    if weight_kg <= 0:
        return annotate_payload(
            {"status": "error", "reason": "invalid_weight_kg"},
            module_name="metabolic_flexibility_engine",
            method="fat_oxidation_rate",
            confidence=0.0,
        )

    # Empirical absolute rate (approximate): g/min ≈ 0.001 × FatMax_watts
    fat_ox_g_per_min = fatmax_watts * 0.001
    fat_ox_mg_per_kg_per_min = (fat_ox_g_per_min * 1000.0) / weight_kg

    # Classify on mass-normalized rate (≈14 / 10 mg·kg⁻¹·min⁻¹ at 70 kg ↔ 1.0 / 0.7 g/min)
    if fat_ox_mg_per_kg_per_min >= 14.0:
        classification = "ELITE"
    elif fat_ox_mg_per_kg_per_min >= 10.0:
        classification = "TRAINED"
    else:
        classification = "RECREATIONAL"

    return annotate_payload(
        {
            "status": "success",
            "fat_oxidation_g_per_min": round(fat_ox_g_per_min, 2),
            "fat_oxidation_mg_per_kg_per_min": round(fat_ox_mg_per_kg_per_min, 2),
            "weight_kg": round(weight_kg, 1),
            "classification": classification,
        },
        module_name="metabolic_flexibility_engine",
        method="fat_oxidation_rate",
        confidence=0.45,
        limitations=[
            "Empirical estimate from FatMax power; not indirect calorimetry.",
            "Classification uses mass-normalized oxidation rate.",
        ],
    )


if __name__ == "__main__":
    mfi = calculate_metabolic_flexibility_index(fatmax_watts=215, vt2_watts=315)
    fat_ox = estimate_fat_oxidation_rate(fatmax_watts=215, weight_kg=75)

    print("Metabolic Flexibility Index:", mfi["mfi"], "→", mfi["classification"])
    print(
        "Fat oxidation rate:",
        fat_ox["fat_oxidation_g_per_min"],
        "g/min;",
        fat_ox["fat_oxidation_mg_per_kg_per_min"],
        "mg/kg/min →",
        fat_ox["classification"],
    )
