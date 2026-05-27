"""
Metabolic Profiler — Phenotype-Adaptive PCr Model
Version: 3.4.0-PhenotypeAdaptive

ENHANCEMENTS:
- PCr capacity and recovery modulated by rider phenotype
- Anaerobic contribution adjusted for sprinter vs climber
- More accurate energy contribution modeling

PHENOTYPE PARAMETERS:
  SPRINTER:     High PCr capacity (25kJ), slower recovery (\u03c4=60s), high anaerobic priority
  TT_CLIMBER:   Low PCr capacity (15kJ), faster recovery (\u03c4=45s), low anaerobic priority
  PURSUITER:    Medium PCr (20kJ), fast recovery (\u03c4=40s), medium anaerobic
  ALL_ROUNDER:  Balanced PCr (20kJ), medium recovery (\u03c4=50s), medium anaerobic
"""

from typing import Dict, Any, Optional
import numpy as np


# =============================================================================
# PHENOTYPE-SPECIFIC PCr PARAMETERS
# =============================================================================

PCr_PARAMS = {
    "SPRINTER": {
        "pcr_capacity_kj": 25.0,
        "recovery_tau_s": 60.0,
        "anaerobic_priority": 0.90,  # Heavily reliant on glycolytic system
        "description": "Explosive fiber profile, large phosphagen stores",
    },
    "TT_CLIMBER": {
        "pcr_capacity_kj": 15.0,
        "recovery_tau_s": 45.0,
        "anaerobic_priority": 0.70,  # More aerobic-efficient
        "description": "Oxidative fiber profile, economical energy use",
    },
    "PURSUITER": {
        "pcr_capacity_kj": 20.0,
        "recovery_tau_s": 40.0,
        "anaerobic_priority": 0.80,
        "description": "Balanced fast-twitch/slow-twitch, rapid recovery",
    },
    "ALL_ROUNDER": {
        "pcr_capacity_kj": 20.0,
        "recovery_tau_s": 50.0,
        "anaerobic_priority": 0.80,
        "description": "Balanced profile across power durations",
    },
    "DEFAULT": {
        "pcr_capacity_kj": 20.0,
        "recovery_tau_s": 50.0,
        "anaerobic_priority": 0.80,
        "description": "Generic athlete without phenotype classification",
    },
}


def get_pcr_params(phenotype: Optional[str]) -> Dict[str, Any]:
    """
    Retrieve PCr parameters for a given rider phenotype.
    
    Parameters:
        phenotype: One of SPRINTER, TT_CLIMBER, PURSUITER, ALL_ROUNDER, or None
    
    Returns:
        Dictionary with pcr_capacity_kj, recovery_tau_s, anaerobic_priority
    """
    if phenotype is None or phenotype not in PCr_PARAMS:
        return PCr_PARAMS["DEFAULT"]
    return PCr_PARAMS[phenotype]


def compute_energy_contribution_adaptive(
    duration_s: float,
    power_w: float,
    vo2max_mlkgmin: float,
    weight_kg: float,
    phenotype: Optional[str] = None,
) -> Dict[str, float]:
    """
    Compute fractional energy contribution from PCr, anaerobic, and aerobic
    systems, modulated by rider phenotype.
    
    Model:
      - PCr: Exponentially decaying, capacity depends on phenotype
      - Anaerobic: Power-dependent, priority depends on phenotype
      - Aerobic: Residual after PCr + anaerobic
    
    Parameters:
        duration_s: Effort duration in seconds
        power_w: Sustained power output
        vo2max_mlkgmin: VO2max in ml/kg/min
        weight_kg: Athlete weight
        phenotype: Rider phenotype (SPRINTER, TT_CLIMBER, etc)
    
    Returns:
        {
            "pcr_fraction": float,
            "anaerobic_fraction": float,
            "aerobic_fraction": float,
            "phenotype_used": str,
        }
    """
    params = get_pcr_params(phenotype)
    
    pcr_capacity_kj = params["pcr_capacity_kj"]
    recovery_tau_s = params["recovery_tau_s"]
    anaerobic_priority = params["anaerobic_priority"]
    
    # Total energy demand
    total_energy_kj = (power_w * duration_s) / 1000.0
    
    # PCr contribution: exponential decay
    # PCr available = capacity × (1 - exp(-t/\u03c4_depletion))
    # Use \u03c4_depletion = 10s (standard literature for maximal efforts)
    tau_depletion = 10.0
    pcr_available_kj = pcr_capacity_kj * (1.0 - np.exp(-duration_s / tau_depletion))
    pcr_contribution_kj = min(pcr_available_kj, total_energy_kj)
    
    # Anaerobic (glycolytic) contribution
    # Depends on intensity and phenotype priority
    # Simplified model: anaerobic covers (power - aerobic_threshold) × priority
    aerobic_capacity_w = (vo2max_mlkgmin * weight_kg * 0.21) / 60.0  # Rough conversion
    power_above_aerobic = max(0, power_w - aerobic_capacity_w * 0.6)  # 60% VO2max threshold
    
    anaerobic_power_w = power_above_aerobic * anaerobic_priority
    anaerobic_contribution_kj = (anaerobic_power_w * duration_s) / 1000.0
    anaerobic_contribution_kj = min(anaerobic_contribution_kj, total_energy_kj - pcr_contribution_kj)
    
    # Aerobic contribution (residual)
    aerobic_contribution_kj = max(0, total_energy_kj - pcr_contribution_kj - anaerobic_contribution_kj)
    
    # Normalize to fractions
    if total_energy_kj > 0:
        pcr_frac = pcr_contribution_kj / total_energy_kj
        anaerobic_frac = anaerobic_contribution_kj / total_energy_kj
        aerobic_frac = aerobic_contribution_kj / total_energy_kj
    else:
        pcr_frac = anaerobic_frac = aerobic_frac = 0.0
    
    return {
        "pcr_fraction": round(pcr_frac, 3),
        "anaerobic_fraction": round(anaerobic_frac, 3),
        "aerobic_fraction": round(aerobic_frac, 3),
        "phenotype_used": phenotype if phenotype in PCr_PARAMS else "DEFAULT",
        "pcr_capacity_kj": pcr_capacity_kj,
        "recovery_tau_s": recovery_tau_s,
    }


def compute_recovery_curve_adaptive(
    max_effort_s: float,
    rest_duration_s: float,
    phenotype: Optional[str] = None,
    sample_rate_s: float = 1.0,
) -> np.ndarray:
    """
    Model PCr recovery curve after maximal effort.
    
    Recovery follows: PCr(t) = PCr_capacity × (1 - exp(-t / \u03c4_recovery))
    
    Parameters:
        max_effort_s: Duration of preceding maximal effort
        rest_duration_s: Duration of recovery period
        phenotype: Rider phenotype
        sample_rate_s: Sampling rate for curve (default 1s)
    
    Returns:
        Array of PCr availability (kJ) over time during recovery
    """
    params = get_pcr_params(phenotype)
    pcr_capacity_kj = params["pcr_capacity_kj"]
    recovery_tau_s = params["recovery_tau_s"]
    
    # Depletion from max effort
    tau_depletion = 10.0
    pcr_depleted = pcr_capacity_kj * (1.0 - np.exp(-max_effort_s / tau_depletion))
    
    # Recovery curve
    t = np.arange(0, rest_duration_s, sample_rate_s)
    pcr_recovered = pcr_depleted * (1.0 - np.exp(-t / recovery_tau_s))
    
    return pcr_recovered


# =============================================================================
# INTEGRATION WITH EXISTING PROFILER
# =============================================================================

def enhance_metabolic_snapshot_with_phenotype(
    snapshot: Dict[str, Any],
    phenotype: Optional[str] = None,
    weight_kg: Optional[float] = None,
    power_30s: Optional[float] = None,
    power_1200s: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Add phenotype-adaptive PCr modeling to an existing metabolic snapshot.
    
    Parameters:
        snapshot:    Output from MetabolicProfiler.generate_metabolic_snapshot()
        phenotype:   Rider phenotype (from coggan_classifier)
        weight_kg:   Athlete weight (not stored in snapshot — pass explicitly).
                     If None, defaults to 75.0.
        power_30s:   Max 30-second power for sprint demo. If None, derived as
                     1.5 × MLSS (rough sprint estimate from threshold).
        power_1200s: Max 20-minute power for threshold demo. If None, defaults
                     to MLSS itself (sustainable threshold output).
    
    Returns:
        Enhanced snapshot with phenotype_pcr_params and energy_contributions
        sections added.
    """
    if not snapshot or snapshot.get("status") != "success":
        return snapshot
    
    params = get_pcr_params(phenotype)
    
    # Add PCr params to snapshot
    snapshot["phenotype_pcr_params"] = {
        "phenotype": phenotype if phenotype in PCr_PARAMS else "DEFAULT",
        "pcr_capacity_kj": params["pcr_capacity_kj"],
        "recovery_tau_s": params["recovery_tau_s"],
        "anaerobic_priority": params["anaerobic_priority"],
        "description": params["description"],
    }
    
    # Read real fields from the snapshot produced by MetabolicProfiler
    vo2max = snapshot.get("estimated_vo2max", 50.0)
    mlss_w = snapshot.get("mlss_power_watts", 250.0)
    
    # Resolve weight (not in snapshot — pass explicitly or default)
    weight = weight_kg if weight_kg is not None else 75.0
    
    # Derive sensible defaults for sprint/threshold power if not supplied.
    # Sprint 30s ≈ 1.5 × MLSS is a rough rule for trained cyclists.
    # 20-min power ≈ MLSS (by definition, sustainable threshold output).
    p30 = power_30s if power_30s is not None else mlss_w * 1.5
    p1200 = power_1200s if power_1200s is not None else mlss_w
    
    sprint_30s = compute_energy_contribution_adaptive(
        duration_s=30.0,
        power_w=p30,
        vo2max_mlkgmin=vo2max,
        weight_kg=weight,
        phenotype=phenotype,
    )
    
    threshold_20min = compute_energy_contribution_adaptive(
        duration_s=1200.0,
        power_w=p1200,
        vo2max_mlkgmin=vo2max,
        weight_kg=weight,
        phenotype=phenotype,
    )
    
    snapshot["energy_contributions"] = {
        "sprint_30s": sprint_30s,
        "threshold_20min": threshold_20min,
    }
    
    return snapshot


if __name__ == "__main__":
    # Demonstration
    print("Metabolic Profiler — Phenotype-Adaptive PCr Model")
    print("=" * 60)
    
    for phenotype in ["SPRINTER", "TT_CLIMBER", "PURSUITER", "ALL_ROUNDER"]:
        params = get_pcr_params(phenotype)
        print(f"\
{phenotype}:")
        print(f"  PCr capacity: {params['pcr_capacity_kj']:.1f} kJ")
        print(f"  Recovery \u03c4: {params['recovery_tau_s']:.0f} s")
        print(f"  Anaerobic priority: {params['anaerobic_priority']:.2f}")
        
        # 30s sprint contribution
        contrib = compute_energy_contribution_adaptive(
            duration_s=30.0,
            power_w=800.0,
            vo2max_mlkgmin=55.0,
            weight_kg=75.0,
            phenotype=phenotype,
        )
        print(f"  30s @ 800W contribution: PCr {contrib['pcr_fraction']:.1%}, "
              f"Anaerobic {contrib['anaerobic_fraction']:.1%}, "
              f"Aerobic {contrib['aerobic_fraction']:.1%}")
    
    print("\
" + "=" * 60)
    print("Recovery curves after 10s maximal sprint:")
    
    import matplotlib.pyplot as plt
    
    fig, ax = plt.subplots(figsize=(10, 6))
    
    for phenotype in ["SPRINTER", "TT_CLIMBER", "PURSUITER"]:
        recovery = compute_recovery_curve_adaptive(
            max_effort_s=10.0,
            rest_duration_s=180.0,
            phenotype=phenotype,
        )
        t = np.arange(len(recovery))
        ax.plot(t, recovery, label=phenotype, linewidth=2)
    
    ax.set_xlabel("Recovery Time (s)", fontsize=12)
    ax.set_ylabel("PCr Recovered (kJ)", fontsize=12)
    ax.set_title("PCr Recovery by Phenotype", fontsize=14, fontweight="bold")
    ax.legend()
    ax.grid(alpha=0.3)
    
    print("Recovery curve plot saved to pcr_recovery_phenotype.png")
    plt.savefig("/tmp/pcr_recovery_phenotype.png", dpi=150, bbox_inches="tight")
    print("(Plot generation would work with matplotlib installed)")
