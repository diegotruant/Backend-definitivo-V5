"""
Mader Durability Engine — CP Residua via Forward ODE
Version: 1.0.0

Stima la CP residua in funzione dei kJ spesi sopra CP durante una sessione,
propagando lo stato metabolico (PCr, lattato) con un forward ODE coerente
con i parametri già stimati da MetabolicProfiler.

FONDAMENTA TEORICHE
-------------------
Nel modello di Mader, W' non è un serbatoio costante: dipende dallo stato
istantaneo del sistema PCr + lattato. Durante una sessione lunga:

  1. PCr si depleta durante gli sforzi sopra soglia e si ricarica parzialmente
     durante il recupero (tau_pcr ~20-22s, rallentato dall'acidosi).

  2. Il lattato accumulato comprime la CP aerobica via inibizione enzimatica
     della glicogenolisi e riduzione del delta-pH per l'ossidoriduzione.

  3. CP_residua(t) = f(PCr_norm, La_excess) — crolla progressivamente con
     il lavoro cumulativo sopra soglia.

DIFFERENZA DAL durability_engine.py ESISTENTE
----------------------------------------------
durability_engine.py è empirico (Riis & Paton 2022): confronta potenza media
prima/ultima ora. Non modella il meccanismo, non dipende dai parametri
fisiologici dell'atleta, non distingue atleti con lo stesso DI ma profili
metabolici diversi.

Questo modulo è meccanicistico: usa vo2max, vlamax, mlss, eta del profilo
atleta per simulare la deplezione metabolica e restituire una CP_residua
che dipende dal profilo fisiologico specifico.

UTILIZZO
--------
from engines.performance.mader_durability import MaderDurabilityEngine

engine = MaderDurabilityEngine(
    weight_kg=80.0,
    vo2max=55.0,          # ml/kg/min — da generate_metabolic_snapshot
    vlamax=0.45,          # mmol/L/s
    mlss_w=260.0,         # Watt — CP proxy
    eta=0.23,             # efficienza meccanica
)

result = engine.compute(power_stream_1hz)

# Output principale
result["cp_residual_curve"]   # CP residua (W) per ogni secondo
result["kj_above_cp_curve"]   # kJ spesi sopra CP (asse x)
result["cp_residual_at_kj"]   # lookup table {kJ: CP_residua}
result["durability_loss_pct"] # % di caduta CP alla fine della sessione
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from engines.core.metric_contracts import annotate_payload


# ---------------------------------------------------------------------------
# Costanti fisiche Mader (identiche a MaderConstants in metabolic_profiler)
# ---------------------------------------------------------------------------

_VO2_BASALE      = 3.5          # ml/kg/min — VO2 a riposo
_EQUIV_O2_LA     = 0.01576      # mmol O2 per mmol lattato
_VOL_REL         = 0.45         # volume distribuzione lattato
_KS1             = 0.0631       # Michaelis-Menten ox-phos
_KS2             = 1.331        # Michaelis-Menten glicolisi
_MLSS_NET_FRAC   = 0.05         # soglia net-production per MLSS

# Cinetica PCr (Forbes 2009, coerente con tau_pcr_rec nei log del progetto)
_TAU_PCR_REC     = 22.0         # s — recupero PCr a pH neutro
_PCR_PH_SLOW     = 0.05         # s extra per mmol/L [La] sopra 4
_PCR_SPRINT_TAU  = 8.0          # s — deplezione PCr durante sprint

# Dimensionamento pool PCr
_PCR_J_PER_W_MLSS = 120.0       # J per W di MLSS (calibrazione interna)
_PCR_MIN_J       = 8_000.0      # J — floor fisiologico
_PCR_MAX_J       = 60_000.0     # J — ceiling fisiologico

# Lattato — clearance e inibizione
_LA_REST         = 1.0          # mmol/L — lattato basale
_LA_INHIBIT_REF  = 4.0          # mmol/L — soglia inizio inibizione CP
_LA_INHIBIT_MAX  = 10.0         # mmol/L — inibizione massima
_CP_INHIBIT_FRAC = 0.20         # frazione max di CP soppressa dall'acidosi

# Soglia sub-massimale — esclude potenza zero (freewheel, semafor, ecc.)
_MIN_POWER_W     = 20.0


# ---------------------------------------------------------------------------
# Dataclass parametri atleta
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DurabilityAthleteParams:
    """
    Parametri fisiologici estratti da generate_metabolic_snapshot().

    Tutti i campi hanno default fisiologicamente ragionevoli per permettere
    istanziazione rapida in test o con dati parziali.
    """
    weight_kg: float          # kg
    vo2max: float             # ml/kg/min
    vlamax: float             # mmol/L/s
    mlss_w: float             # W — Critical Power proxy
    eta: float = 0.23         # efficienza meccanica (tipico 0.21-0.25)
    la_capacity: float = 14.0 # mmol/L — capacità tampone lattato


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class MaderDurabilityEngine:
    """
    Forward ODE metabolico per stima CP_residua durante una sessione intera.

    Parameters
    ----------
    weight_kg : float
    vo2max    : float   ml/kg/min
    vlamax    : float   mmol/L/s
    mlss_w    : float   W (MLSS o CP dal profiler)
    eta       : float   efficienza meccanica (default 0.23)
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
    # API pubblica
    # ------------------------------------------------------------------

    def compute(
        self,
        power_stream: Sequence[float],
        dt: float = 1.0,
        kj_resolution: float = 1.0,
    ) -> Dict[str, Any]:
        """
        Simula la sessione e restituisce la CP residua.

        Parameters
        ----------
        power_stream : sequenza di potenza 1Hz (W)
        dt           : passo temporale in secondi (default 1.0)
        kj_resolution: risoluzione della lookup table in kJ (default 1.0)

        Returns
        -------
        Dict con:
          cp_residual_curve    : List[float] — CP residua (W) per ogni sample
          kj_above_cp_curve    : List[float] — kJ spesi sopra CP per ogni sample
          cp_residual_at_kj    : Dict[int, float] — lookup {kJ: CP_residua}
          durability_loss_pct  : float — % perdita CP fine sessione
          pcr_curve            : List[float] — PCr normalizzato [0,1]
          lactate_curve        : List[float] — lattato stimato (mmol/L)
          session_kj_above_cp  : float — kJ totali spesi sopra CP
          cp_baseline          : float — CP iniziale (W)
          api_contract, uncertainty, tier, tier_explanation
        """
        power = np.asarray(power_stream, dtype=float)
        n = len(power)

        if n < 60:
            return annotate_payload(
                {"status": "insufficient_data", "reason": "Sessione troppo breve (<60s)"},
                module_name="mader_durability",
                method="forward_ode_cp_residual",
                confidence=0.0,
            )

        cp0 = self.p.mlss_w
        pcr_j = self._pcr_max_j          # pool PCr attuale (J)
        la    = _LA_REST                  # lattato corrente (mmol/L)

        cp_curve  = np.empty(n, dtype=float)
        kj_curve  = np.empty(n, dtype=float)
        pcr_norm  = np.empty(n, dtype=float)
        la_curve  = np.empty(n, dtype=float)

        kj_above_cp = 0.0

        for i in range(n):
            p_i = float(power[i])

            # --- Metabolic rates a questa potenza ---
            vo2_req, vla_prod, vla_elim = self._metabolic_rates(p_i)

            # --- PCr dynamics ---
            if p_i > cp0:
                # Deplezione: frazione anaerobica alattacida proporzionale
                # all'eccesso di potenza sopra MAP aerobica
                map_w = self._map_watts()
                p_excess_pcr = max(0.0, p_i - map_w)
                pcr_drain = p_excess_pcr * dt * 0.15     # ~15% eccesso su MAP
                pcr_j = max(0.0, pcr_j - pcr_drain)
            else:
                # Recupero PCr: tau dipende dal pH (proxy: lattato)
                tau_pcr = _TAU_PCR_REC + max(0.0, la - 4.0) * _PCR_PH_SLOW
                pcr_recovery = (self._pcr_max_j - pcr_j) * (1.0 - np.exp(-dt / tau_pcr))
                pcr_j = min(self._pcr_max_j, pcr_j + pcr_recovery)

            # --- Lattato dynamics ---
            # Cap netto a 0.05 mmol/L/s (massimo fisiologico in sprint, Mader 2003).
            # Clearance attiva proporzionale all'eccesso su La_rest.
            la_clear_active = 0.003 * max(0.0, la - _LA_REST)
            net_la_raw = vla_prod - vla_elim - la_clear_active
            net_la_capped = float(np.clip(net_la_raw, -0.08, 0.05))
            la = float(np.clip(la + net_la_capped * dt, _LA_REST, self.p.la_capacity))

            # --- CP_residua ---
            cp_res = self._cp_residual(pcr_j, la, cp0)

            # --- kJ sopra CP ---
            if p_i > cp0 and p_i > _MIN_POWER_W:
                kj_above_cp += (p_i - cp0) * dt / 1000.0

            cp_curve[i]  = cp_res
            kj_curve[i]  = kj_above_cp
            pcr_norm[i]  = pcr_j / self._pcr_max_j
            la_curve[i]  = la

        # --- Lookup table kJ -> CP_residua ---
        # Smooth cp_curve prima del lookup per ridurre oscillazioni da recovery.
        # Finestra 60s: abbastanza larga da smussare recuperi brevi, abbastanza
        # piccola da preservare il trend di deplezione su scala oraria.
        kernel = int(min(60, max(10, len(cp_curve) // 100)))
        cp_smooth = np.convolve(cp_curve, np.ones(kernel) / kernel, mode="same")
        # Fix bordi: i bordi della convoluzione "same" sono distorte; usa i valori originali
        cp_smooth[:kernel//2] = cp_curve[:kernel//2]
        cp_smooth[-(kernel//2):] = cp_curve[-(kernel//2):]
        cp_at_kj = self._build_lookup(kj_curve, cp_smooth, kj_resolution)

        cp_final = float(cp_curve[-1])
        cp_min   = float(np.min(cp_curve))
        # durability_loss_pct: basato sul nadir (cp_min), non sul finale.
        # Il finale può recuperare nel defaticamento; il nadir cattura il
        # momento peggiore della sessione — quello che conta in gara.
        loss_pct = (cp0 - cp_min) / cp0 * 100.0 if cp0 > 0 else 0.0

        # Confidence: cala se la sessione è sub-massimale (poca potenza sopra CP)
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
                "Il pool PCr è stimato da MLSS×120J/W — non calibrato su sprint massimale individuale.",
                "La cinetica di clearance del lattato usa parametri di popolazione.",
                "Confidence cala per sessioni con poca potenza sopra CP (sub-massimale).",
            ],
        )

    # ------------------------------------------------------------------
    # Helpers interni
    # ------------------------------------------------------------------

    def _map_watts(self) -> float:
        """MAP aerobica (potenza a VO2max)."""
        return float(np.clip(
            (self.p.vo2max - _VO2_BASALE) * self.p.weight_kg / 10.8 * (self.p.eta / 0.23),
            50.0, 2500.0,
        ))

    def _metabolic_rates(self, w: float) -> tuple[float, float, float]:
        """
        Restituisce (vo2_act, vla_prod, vla_elim) per una potenza w scalare.
        Logica identica a MetabolicProfiler._metabolic_rates ma scalare.
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
        CP residua in funzione dello stato metabolico corrente.

        Due meccanismi di soppressione:
        1. PCr depletion: W' fosfatico ridotto linearmente con PCr_norm.
           Effetto: riduce il "tetto" anaerobico disponibile, quindi CP effettiva
           cala perché il modello CP/W' assume W' disponibile.
        2. Lactate / acidosi: lattato sopra _LA_INHIBIT_REF comprime CP
           via inibizione enzimatica (analogo all'effetto pH su actomiosina ATPasi).
        """
        # Componente PCr
        pcr_norm = pcr_j / self._pcr_max_j
        # CP dipende dalla quota aerobica (MLSS) + contributo PCr
        # Quando PCr è pieno, CP = cp0. Quando è vuoto, CP cala della
        # quota che il PCr sosteneva (stimata ~10-15% di cp0 per atleti mixed).
        pcr_contribution_frac = 0.08
        cp_pcr = cp0 * (1.0 - pcr_contribution_frac * (1.0 - pcr_norm))

        # Componente lattato / acidosi
        la_excess = max(0.0, la - _LA_INHIBIT_REF)
        la_range = max(1.0, _LA_INHIBIT_MAX - _LA_INHIBIT_REF)
        inhibition = _CP_INHIBIT_FRAC * min(1.0, la_excess / la_range)
        cp_la = cp_pcr * (1.0 - inhibition)

        return float(max(cp0 * 0.40, cp_la))   # floor: CP non scende sotto 40% del baseline

    def _build_lookup(
        self,
        kj_curve: np.ndarray,
        cp_curve: np.ndarray,
        resolution: float,
    ) -> Dict[int, float]:
        """
        Lookup table {kJ_intero: CP_residua_media} campionata ogni `resolution` kJ.
        """
        max_kj = float(kj_curve[-1])
        if max_kj < resolution:
            return {0: round(float(cp_curve[0]), 1)}

        result: Dict[int, float] = {}
        kj_steps = np.arange(0.0, max_kj + resolution, resolution)

        for kj_target in kj_steps:
            # Indici dove kJ spesi sono nell'intorno di kj_target ± resolution/2
            mask = np.abs(kj_curve - kj_target) <= resolution / 2.0
            if mask.any():
                result[int(round(kj_target))] = round(float(np.mean(cp_curve[mask])), 1)

        return result


# ---------------------------------------------------------------------------
# Factory: costruisce l'engine direttamente dall'output di generate_metabolic_snapshot
# ---------------------------------------------------------------------------

def from_metabolic_snapshot(
    snapshot: Dict[str, Any],
    weight_kg: float,
) -> Optional["MaderDurabilityEngine"]:
    """
    Costruisce MaderDurabilityEngine dall'output di MetabolicProfiler.generate_metabolic_snapshot().

    Parameters
    ----------
    snapshot   : dict restituito da generate_metabolic_snapshot()
    weight_kg  : peso atleta in kg

    Returns
    -------
    MaderDurabilityEngine oppure None se i parametri minimi non sono disponibili
    """
    if snapshot.get("status") != "success":
        return None

    unmasked = snapshot.get("unmasked_estimates") or {}
    vo2max = unmasked.get("estimated_vo2max") or snapshot.get("estimated_vo2max")
    vlamax = unmasked.get("estimated_vlamax_mmol_L_s") or snapshot.get("estimated_vlamax_mmol_L_s")
    mlss_w = snapshot.get("mlss_power_watts")

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
# Coaching layer: potenze sostenibili da CP_residua
# ---------------------------------------------------------------------------

def sustainability_targets(
    durability_result: Dict[str, Any],
    *,
    duration_targets_h: tuple[float, ...] = (1.0, 2.0, 3.0, 4.0, 5.0),
    loss_thresholds_pct: tuple[float, ...] = (5.0, 10.0, 15.0),
) -> Dict[str, Any]:
    """
    Traduce cp_residual_at_kj in budget energetici e potenze steady-state
    sostenibili per durata, per pianificare gare lunghe o allenamenti mirati.

    Per ogni soglia di perdita CP (es. 10%), stima la potenza massima costante
    sostenibile per 1-5 h senza superare il budget di kJ sopra CP associato.
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
            "Alta perdita di CP residua: privilegiare volume aerobico sotto soglia "
            "e ridurre blocchi ripetuti sopra MLSS in fase di recupero."
        )
    elif loss_pct >= 8.0:
        focus = (
            "Perdita moderata: utili blocchi soglia brevi; evitare lunghi tratti "
            "continui sopra MLSS quando la CP residua è già compressa."
        )
    else:
        focus = (
            "Buona resistenza metabolica: profilo adatto a blocchi soglia e lavoro "
            "prolungato moderato sopra la base aerobica."
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
            "Potenze sostenibili = stima a regime costante: a parità di kJ sopra CP, "
            "la CP residua meccanicistica non scende oltre la soglia di perdita indicata."
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
    Pipeline unica: profilo metabolico → forward ODE → target di sostenibilità.

    Usata da workout_summary, session_router e audit batch.
    """
    engine = from_metabolic_snapshot(metabolic_snapshot, weight_kg)
    if engine is None:
        return annotate_payload(
            {
                "status": "unavailable",
                "reason": "missing_metabolic_profile",
                "message": (
                    "Servono VO2max, VLamax e MLSS da generate_metabolic_snapshot() "
                    "per la durability meccanicistica Mader."
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

if __name__ == "__main__":
    import json

    print("=" * 70)
    print("MADER DURABILITY ENGINE — Self-test")
    print("=" * 70)

    # Profilo: atleta all-rounder 75kg, VO2max 55, VLamax 0.45, MLSS 265W
    engine = MaderDurabilityEngine(
        weight_kg=75.0,
        vo2max=55.0,
        vlamax=0.45,
        mlss_w=265.0,
        eta=0.23,
        la_capacity=14.0,
    )

    rng = np.random.default_rng(42)
    duration_s = 3 * 3600   # 3 ore

    # Sessione realistica: riscaldamento + zona 3 + 3 scatti + defaticamento
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
    print(f"CP finale         : {result['cp_final']:.0f} W")
    print(f"Perdita durability: {result['durability_loss_pct']:.1f}%")
    print(f"kJ spesi sopra CP : {result['session_kj_above_cp']:.1f} kJ")
    unc = result["uncertainty"]
    conf_score = unc.get("confidence_score", unc) if isinstance(unc, dict) else unc
    print(f"Confidence        : {conf_score:.2f}")

    print("\nLookup CP_residua @ kJ spesi sopra CP:")
    lookup = result["cp_residual_at_kj"]
    for kj in sorted(lookup.keys()):
        if kj % 5 == 0:
            print(f"  {kj:4d} kJ → {lookup[kj]:.0f} W")

    # Test con atleta ad alta VLamax (sprinter) — deve perdere CP più velocemente
    engine_sprinter = MaderDurabilityEngine(
        weight_kg=80.0, vo2max=48.0, vlamax=0.80,
        mlss_w=220.0, eta=0.22,
    )
    r2 = engine_sprinter.compute(power)
    print(f"\nSprinter (VLamax=0.80): perdita {r2['durability_loss_pct']:.1f}% vs {result['durability_loss_pct']:.1f}% all-rounder")
    print("\n[OK] Self-test completato")
