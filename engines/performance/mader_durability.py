"""
Mader Durability Engine — Residual CP via Forward ODE
Version: 1.0.0

Estimates residual CP as a function of kJ spent above CP during a session,
propagating metabolic state (PCr, lactate) with a forward ODE consistent
with parameters already estimated by MetabolicProfiler.

THEORETICAL FOUNDATIONS
-----------------------
In the Mader model, W' is not a constant reservoir: it depends on the
instantaneous state of the PCr + lactate system. During a long session:

  1. PCr depletes during efforts above threshold and partially recharges
     during recovery (tau_pcr ~20-22s, slowed by acidosis).

  2. Accumulated lactate compresses aerobic CP via enzymatic inhibition
     of glycogenolysis and reduced delta-pH for oxidation-reduction.

  3. CP_residual(t) = f(PCr_norm, La_excess) — progressively declines with
     cumulative work above threshold.

DIFFERENCE FROM EXISTING durability_engine.py
----------------------------------------------
durability_engine.py is empirical (Riis & Paton 2022): it compares mean power
in the first vs. last hour. It does not model the mechanism, does not depend on
the athlete's physiological parameters, and does not distinguish athletes with
the same DI but different metabolic profiles.

This module is mechanistic: it uses vo2max, vlamax, mlss, and eta from the
athlete profile to simulate metabolic depletion and return a CP_residual
that depends on the specific physiological profile.

USAGE
-----
from engines.performance.mader_durability import MaderDurabilityEngine

engine = MaderDurabilityEngine(
    weight_kg=80.0,
    vo2max=55.0,          # ml/kg/min — from generate_metabolic_snapshot
    vlamax=0.45,          # mmol/L/s
    mlss_w=260.0,         # W — CP proxy
    eta=0.23,             # mechanical efficiency
)

result = engine.compute(power_stream_1hz)

# Primary outputs
result["cp_residual_curve"]   # residual CP (W) for each second
result["kj_above_cp_curve"]   # kJ spent above CP (x-axis)
result["cp_residual_at_kj"]   # lookup table {kJ: CP_residual}
result["durability_loss_pct"] # % CP drop at end of session
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence

import numpy as np

from engines.core.metric_contracts import annotate_payload


# ---------------------------------------------------------------------------
# Mader physical constants (identical to MaderConstants in metabolic_profiler)
# ---------------------------------------------------------------------------

_VO2_BASALE      = 3.5          # ml/kg/min — resting VO2
_EQUIV_O2_LA     = 0.01576      # mmol O2 per mmol lactate
_VOL_REL         = 0.45         # lactate distribution volume
_KS1             = 0.0631       # Michaelis-Menten ox-phos
_KS2             = 1.331        # Michaelis-Menten glycolysis
_MLSS_NET_FRAC   = 0.05         # net-production threshold for MLSS

# PCr kinetics (Forbes 2009, consistent with tau_pcr_rec in project logs)
_TAU_PCR_REC     = 22.0         # s — PCr recovery at neutral pH
_PCR_PH_SLOW     = 0.05         # s extra per mmol/L [La] above 4
_PCR_SPRINT_TAU  = 8.0          # s — PCr depletion during sprint

# PCr pool sizing
_PCR_J_PER_W_MLSS = 120.0       # J per W of MLSS (internal calibration)
_PCR_MIN_J       = 8_000.0      # J — physiological floor
_PCR_MAX_J       = 60_000.0     # J — physiological ceiling

# Lactate — clearance and inhibition
_LA_REST         = 1.0          # mmol/L — basal lactate
_LA_INHIBIT_REF  = 4.0          # mmol/L — threshold for onset of CP inhibition
_LA_INHIBIT_MAX  = 10.0         # mmol/L — maximum inhibition
_CP_INHIBIT_FRAC = 0.20         # max fraction of CP suppressed by acidosis

# Sub-maximal threshold — excludes zero power (freewheel, stoplight, etc.)
_MIN_POWER_W     = 20.0


# ---------------------------------------------------------------------------
# Athlete parameters dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DurabilityAthleteParams:
    """
    Physiological parameters extracted from generate_metabolic_snapshot().

    All fields have physiologically reasonable defaults to allow quick
    instantiation in tests or with partial data.
    """
    weight_kg: float          # kg
    vo2max: float             # ml/kg/min
    vlamax: float             # mmol/L/s
    mlss_w: float             # W — Critical Power proxy
    eta: float = 0.23         # mechanical efficiency (typical 0.21-0.25)
    la_capacity: float = 14.0 # mmol/L — lactate buffering capacity


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class MaderDurabilityEngine:
    """
    Metabolic forward ODE for estimating CP_residual over a full session.

    Parameters
    ----------
    weight_kg : float
    vo2max    : float   ml/kg/min
    vlamax    : float   mmol/L/s
    mlss_w    : float   W (MLSS or CP from profiler)
    eta       : float   mechanical efficiency (default 0.23)
    la_capacity : float mmol/L (default 14.0)
    """

    def __init__(
        self,
        weight_kg: float,
        vo2max: float,
        vlamax: float,
        mlss_w: float,
        eta: float = 0.23,
        la_capacity: float = 14.0,
    ) -> None:
        self.p = DurabilityAthleteParams(
            weight_kg=weight_kg,
            vo2max=vo2max,
            vlamax=vlamax,
            mlss_w=mlss_w,
            eta=eta,
            la_capacity=la_capacity,
        )
        self._pcr_max_j = float(np.clip(
            mlss_w * _PCR_J_PER_W_MLSS,
            _PCR_MIN_J,
            _PCR_MAX_J,
        ))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute(
        self,
        power_stream: Sequence[float],
        dt: float = 1.0,
        kj_resolution: float = 1.0,
    ) -> Dict[str, Any]:
        """
        Simulate the session and return residual CP.

        Parameters
        ----------
        power_stream : 1 Hz power sequence (W)
        dt           : time step in seconds (default 1.0)
        kj_resolution: lookup table resolution in kJ (default 1.0)

        Returns
        -------
        Dict with:
          cp_residual_curve    : List[float] — residual CP (W) per sample
          kj_above_cp_curve    : List[float] — kJ spent above CP per sample
          cp_residual_at_kj    : Dict[int, float] — lookup {kJ: CP_residual}
          durability_loss_pct  : float — % CP loss at end of session
          pcr_curve            : List[float] — normalized PCr [0,1]
          lactate_curve        : List[float] — estimated lactate (mmol/L)
          session_kj_above_cp  : float — total kJ spent above CP
          cp_baseline          : float — initial CP (W)
          api_contract, uncertainty, tier, tier_explanation
        """
        power = np.asarray(power_stream, dtype=float)
        n = len(power)

        if n < 60:
            return annotate_payload(
                {"status": "insufficient_data", "reason": "Session too short (<60s)"},
                module_name="mader_durability",
                method="forward_ode_cp_residual",
                confidence=0.0,
            )

        cp0 = self.p.mlss_w
        pcr_j = self._pcr_max_j          # current PCr pool (J)
        la    = _LA_REST                  # current lactate (mmol/L)

        cp_curve  = np.empty(n, dtype=float)
        kj_curve  = np.empty(n, dtype=float)
        pcr_norm  = np.empty(n, dtype=float)
        la_curve  = np.empty(n, dtype=float)

        kj_above_cp = 0.0

        for i in range(n):
            p_i = float(power[i])

            # --- Metabolic rates at this power ---
            vo2_req, vla_prod, vla_elim = self._metabolic_rates(p_i)

            # --- PCr dynamics ---
            if p_i > cp0:
                # Depletion: alactic anaerobic fraction proportional to
                # power excess above aerobic MAP
                map_w = self._map_watts()
                p_excess_pcr = max(0.0, p_i - map_w)
                pcr_drain = p_excess_pcr * dt * 0.15     # ~15% excess above MAP
                pcr_j = max(0.0, pcr_j - pcr_drain)
            else:
                # PCr recovery: tau depends on pH (proxy: lactate)
                tau_pcr = _TAU_PCR_REC + max(0.0, la - 4.0) * _PCR_PH_SLOW
                pcr_recovery = (self._pcr_max_j - pcr_j) * (1.0 - np.exp(-dt / tau_pcr))
                pcr_j = min(self._pcr_max_j, pcr_j + pcr_recovery)

            # --- Lactate dynamics ---
            # Net cap at 0.05 mmol/L/s (physiological maximum in sprint, Mader 2003).
            # Active clearance proportional to excess above La_rest.
            la_clear_active = 0.003 * max(0.0, la - _LA_REST)
            net_la_raw = vla_prod - vla_elim - la_clear_active
            net_la_capped = float(np.clip(net_la_raw, -0.08, 0.05))
            la = float(np.clip(la + net_la_capped * dt, _LA_REST, self.p.la_capacity))

            # --- CP_residual ---
            cp_res = self._cp_residual(pcr_j, la, cp0)

            # --- kJ above CP ---
            if p_i > cp0 and p_i > _MIN_POWER_W:
                kj_above_cp += (p_i - cp0) * dt / 1000.0

            cp_curve[i]  = cp_res
            kj_curve[i]  = kj_above_cp
            pcr_norm[i]  = pcr_j / self._pcr_max_j
            la_curve[i]  = la

        # --- Lookup table kJ -> CP_residual ---
        # Smooth cp_curve before lookup to reduce recovery oscillations.
        # 60s window: wide enough to smooth brief recoveries, narrow enough
        # to preserve depletion trend on hourly scale.
        kernel = int(min(60, max(10, len(cp_curve) // 100)))
        cp_smooth = np.convolve(cp_curve, np.ones(kernel) / kernel, mode="same")
        # Edge fix: "same" convolution edges are distorted; use original values
        cp_smooth[:kernel//2] = cp_curve[:kernel//2]
        cp_smooth[-(kernel//2):] = cp_curve[-(kernel//2):]
        cp_at_kj = self._build_lookup(kj_curve, cp_smooth, kj_resolution)

        cp_final = float(cp_curve[-1])
        cp_min   = float(np.min(cp_curve))
        # durability_loss_pct: based on nadir (cp_min), not final value.
        # Final value may recover during cooldown; nadir captures the
        # worst point of the session — what matters in competition.
        loss_pct = (cp0 - cp_min) / cp0 * 100.0 if cp0 > 0 else 0.0

        # Confidence: decreases for sub-maximal sessions (little power above CP)
        pct_above_cp = float(np.mean(power[power > _MIN_POWER_W] > cp0)) if np.any(power > _MIN_POWER_W) else 0.0
        confidence = float(np.clip(0.40 + 0.50 * pct_above_cp, 0.20, 0.90))

        result = {
            "status": "success",
            "cp_baseline": round(cp0, 1),
            "cp_residual_curve": [round(v, 1) for v in cp_curve],
            "kj_above_cp_curve": [round(v, 2) for v in kj_curve],
            "cp_residual_at_kj": cp_at_kj,
            "durability_loss_pct": round(loss_pct, 1),
            "cp_final": round(cp_final, 1),
            "cp_min": round(cp_min, 1),
            "session_kj_above_cp": round(float(kj_above_cp), 1),
            "pcr_curve": [round(float(v), 3) for v in pcr_norm],
            "lactate_curve": [round(float(v), 2) for v in la_curve],
            "params_used": {
                "weight_kg": self.p.weight_kg,
                "vo2max": self.p.vo2max,
                "vlamax": self.p.vlamax,
                "mlss_w": self.p.mlss_w,
                "eta": self.p.eta,
                "pcr_max_j": round(self._pcr_max_j, 0),
            },
        }

        return annotate_payload(
            result,
            module_name="mader_durability",
            method="forward_ode_cp_residual",
            confidence=confidence,
            limitations=[
                "PCr pool is estimated from MLSS×120J/W — not calibrated to individual maximal sprint.",
                "Lactate clearance kinetics use population-level parameters.",
                "Confidence decreases for sessions with little power above CP (sub-maximal).",
            ],
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _map_watts(self) -> float:
        """Aerobic MAP (power at VO2max)."""
        return float(np.clip(
            (self.p.vo2max - _VO2_BASALE) * self.p.weight_kg / 10.8 * (self.p.eta / 0.23),
            50.0, 2500.0,
        ))

    def _metabolic_rates(self, w: float) -> tuple[float, float, float]:
        """
        Return (vo2_act, vla_prod, vla_elim) for a scalar power w.
        Logic identical to MetabolicProfiler._metabolic_rates but scalar.
        """
        coeff = 10.8 * (0.23 / self.p.eta)
        vo2_req = _VO2_BASALE + coeff * (w / self.p.weight_kg)
        vo2_act = min(vo2_req, self.p.vo2max - 1e-9)

        denom = max(1e-9, self.p.vo2max - vo2_act)
        adp = np.sqrt((_KS1 * vo2_act) / denom)
        vla_prod = self.p.vlamax / (1.0 + (_KS2 / max(1e-9, adp ** 3)))
        vla_elim = (_EQUIV_O2_LA * max(0.0, vo2_act - _VO2_BASALE)) / (_VOL_REL * 60.0)

        return float(vo2_act), float(vla_prod), float(vla_elim)

    def _cp_residual(self, pcr_j: float, la: float, cp0: float) -> float:
        """
        Residual CP as a function of current metabolic state.

        Two suppression mechanisms:
        1. PCr depletion: phosphocreatine W' reduced linearly with PCr_norm.
           Effect: reduces available anaerobic ceiling, so effective CP
           falls because the CP/W' model assumes W' is available.
        2. Lactate / acidosis: lactate above _LA_INHIBIT_REF compresses CP
           via enzymatic inhibition (analogous to pH effect on actomyosin ATPase).
        """
        # PCr component
        pcr_norm = pcr_j / self._pcr_max_j
        # CP depends on aerobic share (MLSS) + PCr contribution
        # When PCr is full, CP = cp0. When depleted, CP falls by the
        # share PCr was supporting (estimated ~10-15% of cp0 for mixed athletes).
        pcr_contribution_frac = 0.08
        cp_pcr = cp0 * (1.0 - pcr_contribution_frac * (1.0 - pcr_norm))

        # Lactate / acidosis component
        la_excess = max(0.0, la - _LA_INHIBIT_REF)
        la_range = max(1.0, _LA_INHIBIT_MAX - _LA_INHIBIT_REF)
        inhibition = _CP_INHIBIT_FRAC * min(1.0, la_excess / la_range)
        cp_la = cp_pcr * (1.0 - inhibition)

        return float(max(cp0 * 0.40, cp_la))   # floor: CP does not fall below 40% of baseline

    def _build_lookup(
        self,
        kj_curve: np.ndarray,
        cp_curve: np.ndarray,
        resolution: float,
    ) -> Dict[int, float]:
        """
        Lookup table {integer_kJ: mean_CP_residual} sampled every `resolution` kJ.
        """
        max_kj = float(kj_curve[-1])
        if max_kj < resolution:
            return {0: round(float(cp_curve[0]), 1)}

        result: Dict[int, float] = {}
        kj_steps = np.arange(0.0, max_kj + resolution, resolution)

        for kj_target in kj_steps:
            # Indices where kJ spent are within kj_target ± resolution/2
            mask = np.abs(kj_curve - kj_target) <= resolution / 2.0
            if mask.any():
                result[int(round(kj_target))] = round(float(np.mean(cp_curve[mask])), 1)

        return result


# ---------------------------------------------------------------------------
# Factory: builds the engine directly from generate_metabolic_snapshot output
# ---------------------------------------------------------------------------

def from_metabolic_snapshot(
    snapshot: Dict[str, Any],
    weight_kg: float,
) -> Optional["MaderDurabilityEngine"]:
    """
    Build MaderDurabilityEngine from MetabolicProfiler.generate_metabolic_snapshot() output.

    Parameters
    ----------
    snapshot   : dict returned by generate_metabolic_snapshot()
    weight_kg  : athlete weight in kg

    Returns
    -------
    MaderDurabilityEngine or None if minimum parameters are unavailable
    """
    if snapshot.get("status") != "success":
        return None

    unmasked = snapshot.get("unmasked_estimates") or {}
    vo2max = unmasked.get("estimated_vo2max") or snapshot.get("estimated_vo2max")
    vlamax = unmasked.get("estimated_vlamax_mmol_L_s") or snapshot.get("estimated_vlamax_mmol_L_s")
    mlss_w = unmasked.get("mlss_power_watts") or snapshot.get("mlss_power_watts")

    if any(v is None for v in [vo2max, vlamax, mlss_w]):
        return None

    ctx_used = snapshot.get("context_used") or {}
    eta = ctx_used.get("resolved_eta", 0.23)
    la_cap = snapshot.get("assumed_la_capacity_mmol_L", 14.0)

    return MaderDurabilityEngine(
        weight_kg=float(weight_kg),
        vo2max=float(vo2max),
        vlamax=float(vlamax),
        mlss_w=float(mlss_w),
        eta=float(eta),
        la_capacity=float(la_cap),
    )


# ---------------------------------------------------------------------------
# Coaching layer: sustainable power from CP_residual
# ---------------------------------------------------------------------------

def sustainability_targets(
    durability_result: Dict[str, Any],
    *,
    duration_targets_h: tuple[float, ...] = (1.0, 2.0, 3.0, 4.0, 5.0),
    loss_thresholds_pct: tuple[float, ...] = (5.0, 10.0, 15.0),
) -> Dict[str, Any]:
    """
    Translate cp_residual_at_kj into energy budgets and duration-specific
    sustainable steady-state power for long-race planning or targeted training.

    For each CP loss threshold (e.g. 10%), estimates the maximum constant power
    sustainable for 1-5 h without exceeding the associated kJ-above-CP budget.
    """
    if durability_result.get("status") != "success":
        return {"status": "unavailable", "reason": "durability_compute_failed"}

    cp0 = float(durability_result["cp_baseline"])
    lookup = durability_result.get("cp_residual_at_kj") or {}
    if not lookup:
        return {"status": "unavailable", "reason": "empty_cp_residual_lookup"}

    kj_budgets: Dict[str, float] = {}
    for loss in loss_thresholds_pct:
        floor = cp0 * (1.0 - loss / 100.0)
        eligible = [float(kj) for kj, cp in lookup.items() if float(cp) >= floor]
        kj_budgets[f"max_kj_before_{int(loss)}pct_cp_loss"] = max(eligible) if eligible else 0.0

    sustainable_power_w: Dict[str, Dict[str, float]] = {}
    for loss in loss_thresholds_pct:
        max_kj = kj_budgets[f"max_kj_before_{int(loss)}pct_cp_loss"]
        band: Dict[str, float] = {}
        for dh in duration_targets_h:
            if max_kj <= 0:
                band[f"{dh:g}h"] = round(cp0, 0)
            else:
                # kJ_above_cp = (P - cp0) * duration_h * 3.6  (P in W, h in ore)
                p_max = cp0 + max_kj / (dh * 3.6)
                band[f"{dh:g}h"] = round(min(p_max, cp0 * 1.40), 0)
        sustainable_power_w[f"at_{int(loss)}pct_cp_loss"] = band

    loss_pct = float(durability_result.get("durability_loss_pct") or 0.0)
    if loss_pct >= 15.0:
        focus = (
            "High residual CP loss: prioritize sub-threshold aerobic volume "
            "and reduce repeated blocks above MLSS during recovery phases."
        )
    elif loss_pct >= 8.0:
        focus = (
            "Moderate loss: short threshold blocks are useful; avoid long continuous "
            "segments above MLSS when residual CP is already compressed."
        )
    else:
        focus = (
            "Good metabolic durability: profile suited to threshold blocks and "
            "sustained moderate work above aerobic base."
        )

    return {
        "status": "success",
        "cp_baseline_w": cp0,
        "kj_budgets": kj_budgets,
        "sustainable_steady_power_w": sustainable_power_w,
        "session_kj_above_cp": durability_result.get("session_kj_above_cp"),
        "durability_loss_pct": loss_pct,
        "cp_nadir_w": durability_result.get("cp_min"),
        "cp_final_w": durability_result.get("cp_final"),
        "training_recommendations": [focus],
        "interpretation": (
            "Sustainable powers = steady-state estimate: for a given kJ above CP, "
            "mechanistic residual CP does not fall below the indicated loss threshold."
        ),
    }


def compute_session_durability(
    power_stream: Sequence[float],
    metabolic_snapshot: Dict[str, Any],
    weight_kg: float,
    *,
    dt: float = 1.0,
    kj_resolution: float = 1.0,
) -> Dict[str, Any]:
    """
    Single pipeline: metabolic profile → forward ODE → sustainability targets.

    Used by workout_summary, session_router, and audit batch.
    """
    engine = from_metabolic_snapshot(metabolic_snapshot, weight_kg)
    if engine is None:
        return annotate_payload(
            {
                "status": "unavailable",
                "reason": "missing_metabolic_profile",
                "message": (
                    "VO2max, VLamax, and MLSS from generate_metabolic_snapshot() "
                    "are required for Mader mechanistic durability."
                ),
            },
            module_name="mader_durability",
            method="compute_session_durability",
            confidence=0.0,
        )

    result = engine.compute(power_stream, dt=dt, kj_resolution=kj_resolution)
    if result.get("status") != "success":
        return result

    sustainability = sustainability_targets(result)
    result["sustainability"] = sustainability
    return result


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover

    print("=" * 70)
    print("MADER DURABILITY ENGINE — Self-test")
    print("=" * 70)

    # Profile: all-rounder athlete 75kg, VO2max 55, VLamax 0.45, MLSS 265W
    engine = MaderDurabilityEngine(
        weight_kg=75.0,
        vo2max=55.0,
        vlamax=0.45,
        mlss_w=265.0,
        eta=0.23,
        la_capacity=14.0,
    )

    rng = np.random.default_rng(42)
    duration_s = 3 * 3600   # 3 hours

    # Realistic session: warmup + zone 3 + 3 surges + cooldown
    warmup   = np.full(1800, 150.0)                                          # 30 min Z1
    base     = rng.normal(230.0, 15.0, 3600).clip(150, 400)                 # 1h Z2
    intervals = np.concatenate([
        np.full(300, 310.0), np.full(300, 160.0),  # 2× 5min threshold
        np.full(300, 320.0), np.full(300, 160.0),
        np.full(300, 330.0), np.full(300, 160.0),
    ])
    cooldown = np.full(1200, 130.0)

    power = np.concatenate([warmup, base, intervals, cooldown])

    result = engine.compute(power)

    print(f"\nCP baseline       : {result['cp_baseline']:.0f} W")
    print(f"Final CP          : {result['cp_final']:.0f} W")
    print(f"Durability loss   : {result['durability_loss_pct']:.1f}%")
    print(f"kJ above CP       : {result['session_kj_above_cp']:.1f} kJ")
    unc = result["uncertainty"]
    conf_score = unc.get("confidence_score", unc) if isinstance(unc, dict) else unc
    print(f"Confidence        : {conf_score:.2f}")

    print("\nLookup CP_residual @ kJ spent above CP:")
    lookup = result["cp_residual_at_kj"]
    for kj in sorted(lookup.keys()):
        if kj % 5 == 0:
            print(f"  {kj:4d} kJ → {lookup[kj]:.0f} W")

    # Test with high-VLamax athlete (sprinter) — should lose CP faster
    engine_sprinter = MaderDurabilityEngine(
        weight_kg=80.0, vo2max=48.0, vlamax=0.80,
        mlss_w=220.0, eta=0.22,
    )
    r2 = engine_sprinter.compute(power)
    print(f"\nSprinter (VLamax=0.80): loss {r2['durability_loss_pct']:.1f}% vs {result['durability_loss_pct']:.1f}% all-rounder")
    print("\n[OK] Self-test completed")
