"""
Interval Detector & Session Classifier
=======================================

Classifies a workout into one of 4 macro-categories (TEST, HIIT, STEADY, FREE)
with a sub-type, and extracts:
  - **Qualified MMP anchors** (when TEST) → input to MetabolicProfiler with
    high `anchor_reliability` weight (the route to lifting confidence on
    athletes whose MMP comes mostly from un-qualified rolling windows).
  - **Stimulus vector** (when HIIT) → time above VO2max / threshold /
    anaerobic, time-on, work-rest ratio, microburst count. Input to the
    future multi-parametric detraining model (v3.5.0).

Three-strategy cascade with declared confidence:
  Strategy A — Filename match     (confidence 1.00, source="filename")
  Strategy B — Lap structure      (confidence 0.80, source="laps")
  Strategy C — Signal features    (confidence 0.40-0.60, source="signal")
  Fallback   — "UNCLASSIFIED"     (confidence 0.00, requires human review)

A is preferred when the file naming convention is parlante (e.g.
`activity_..._ramp_test_01.fit`). B is used when the FIT has structured
laps (≥10 laps with regular durations). C is the last resort when
neither A nor B applies.

This module is ADDITIVE — it does not change any existing engine's behaviour
in v3.4.0. The integration into MetabolicProfiler (`anchor_reliability`-aware
fit) and detraining_engine (multi-parametric decay) is deferred to v3.5.0.

Tier
----
Pattern detection (segmentation, lap analysis) — REFERENCE
Subtype classification (mapping pattern → physiological intent) — MODEL
Stimulus vector (time-in-zones) — REFERENCE (given thresholds known)

Inspired by
-----------
- Interval-classification workflows — change-point detection + post-processing
- external analysis platforms — zone × duration matching
- Sliding-window best-interval extraction — MMP scan
- Buchheit & Laursen 2013 — HIIT prescription framework (work:rest semantics)
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import re
import math
from pathlib import Path


# =============================================================================
# Public types
# =============================================================================

class Category(str, Enum):
    """Top-level session classification."""
    TEST = "TEST"
    HIIT = "HIIT"
    STEADY = "STEADY"
    FREE = "FREE"
    UNCLASSIFIED = "UNCLASSIFIED"


# Subtypes (closed taxonomy as discussed with the user)
SUBTYPES_TEST = frozenset({
    "ramp_test",
    "ftp_2x8", "ftp_20min", "ftp_8min",
    "cp3", "cp6", "cp12", "cp_test",
    "single_sprint", "sprint_set",
    "mixed_test",
})
SUBTYPES_HIIT = frozenset({
    "microburst_high_density",    # work<60s, ratio work:rest ≥1.5
    "microburst_balanced",        # work<60s, ratio ≈1
    "medium_interval",            # work 1-3min
    "long_interval",              # work ≥3min, ratio ≤1.5
    "sprint_repeats",             # work <15s, multiple reps
    "structured_mixed",           # multiple block types
    "hiit_unspecified",           # generic HIIT, no specific pattern
})
SUBTYPES_STEADY = frozenset({
    "endurance_z2", "tempo", "sweet_spot", "threshold_continuous",
})
SUBTYPES_FREE = frozenset({
    "race", "group_ride", "free_ride",
})


@dataclass
class QualifiedAnchor:
    """An MMP anchor from a qualified test, with full provenance."""
    duration_s: int
    power_w: float
    anchor_reliability: float    # 1.0 = direct all-out test, 0.5 = inferred
    source_subtype: str           # which test produced it
    notes: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class IntervalBlock:
    """A detected block within a HIIT session."""
    start_s: int
    end_s: int
    duration_s: int
    pattern: Dict[str, Any]       # {work_s, rest_s, cycles, work_w, rest_w, ratio}
    classification: str           # one of SUBTYPES_HIIT
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class StimulusVector:
    """Time-in-zone vector for a session."""
    total_time_s: int = 0
    aerobic_base_stimulus_s: int = 0       # <75% FTP
    tempo_stimulus_s: int = 0              # 75-90% FTP
    threshold_stimulus_s: int = 0          # 90-105% FTP
    vo2max_stimulus_s: int = 0             # 105-120% FTP
    anaerobic_stimulus_s: int = 0          # 120-150% FTP
    neuromuscular_stimulus_s: int = 0      # >150% FTP
    
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["aerobic_base_min"] = round(self.aerobic_base_stimulus_s / 60, 1)
        d["tempo_min"] = round(self.tempo_stimulus_s / 60, 1)
        d["threshold_min"] = round(self.threshold_stimulus_s / 60, 1)
        d["vo2max_min"] = round(self.vo2max_stimulus_s / 60, 1)
        d["anaerobic_min"] = round(self.anaerobic_stimulus_s / 60, 1)
        d["neuromuscular_min"] = round(self.neuromuscular_stimulus_s / 60, 1)
        return d


@dataclass
class ClassifiedSession:
    """The full output of classify_session()."""
    category: str                          # Category enum value
    subtype: str                           # e.g. "ramp_test", "microburst_high_density"
    confidence: float                       # 0..1
    source: str                            # "filename", "laps", "signal", "fallback"
    notes: List[str] = field(default_factory=list)
    
    # Only meaningful when category == TEST
    qualified_anchors: List[QualifiedAnchor] = field(default_factory=list)
    
    # Only meaningful when category == HIIT (blocks may be empty even if HIIT)
    detected_blocks: List[IntervalBlock] = field(default_factory=list)
    
    # Always computed (zone-time based on ftp)
    stimulus_vector: Optional[StimulusVector] = None
    
    # Diagnostic
    duration_s: int = 0
    avg_power_w: float = 0.0
    normalized_power_w: float = 0.0
    variability_index: float = 0.0
    intensity_factor: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "subtype": self.subtype,
            "confidence": round(self.confidence, 3),
            "source": self.source,
            "notes": self.notes,
            "qualified_anchors": [a.to_dict() for a in self.qualified_anchors],
            "detected_blocks": [b.to_dict() for b in self.detected_blocks],
            "stimulus_vector": self.stimulus_vector.to_dict() if self.stimulus_vector else None,
            "duration_s": self.duration_s,
            "duration_min": round(self.duration_s / 60, 1),
            "avg_power_w": round(self.avg_power_w, 1),
            "normalized_power_w": round(self.normalized_power_w, 1),
            "variability_index": round(self.variability_index, 3),
            "intensity_factor": round(self.intensity_factor, 3),
            "tier": "MODEL",  # subtype mapping is a model judgement
        }


# =============================================================================
# Strategy A — Filename match
# =============================================================================

# Order matters: more specific patterns come first.
# Each tuple: (regex, category, subtype, confidence)
_FILENAME_PATTERNS: List[Tuple[str, str, str, float]] = [
    # Tests — most specific first
    (r"ramp[_\-]?test|ramp\d|ramp_protocol",     "TEST",  "ramp_test",     1.00),
    (r"ftp[_\-]?2x8|2x8[_\-]?test|2x8[_\-]?ftp", "TEST",  "ftp_2x8",       1.00),
    (r"ftp[_\-]?20[_\-]?min|20min[_\-]?test",    "TEST",  "ftp_20min",     1.00),
    (r"ftp[_\-]?8[_\-]?min|8min[_\-]?test",      "TEST",  "ftp_8min",      1.00),
    (r"ftp[_\-]?test",                            "TEST",  "ftp_20min",     0.90),
    (r"cp[_\-]?3|cp3[_\-]?test|3min[_\-]?test",  "TEST",  "cp3",           1.00),
    (r"cp[_\-]?6|cp6[_\-]?test|6min[_\-]?test",  "TEST",  "cp6",           1.00),
    (r"cp[_\-]?12|cp12[_\-]?test|12min[_\-]?test","TEST", "cp12",          1.00),
    (r"sprint[_\-]?set|sprint[_\-]?repeats",      "TEST",  "sprint_set",    1.00),
    (r"3[_\-]?sprint",                            "TEST",  "sprint_set",    1.00),
    (r"sprint[_\-]?test|sprint[_\-]?protocol",    "TEST",  "single_sprint", 1.00),
    (r"flow[_\-]?protocol|combined[_\-]?test|mixed[_\-]?test",
                                                  "TEST",  "mixed_test",    1.00),
    
    # HIIT — common protocol names
    (r"30[_\-]?15|30/15",                         "HIIT",  "microburst_high_density", 1.00),
    (r"40[_\-]?20|40/20",                         "HIIT",  "microburst_high_density", 1.00),
    (r"30[_\-]?30|30/30",                         "HIIT",  "microburst_balanced",     1.00),
    (r"15[_\-]?15|15/15",                         "HIIT",  "microburst_balanced",     1.00),
    (r"tabata",                                   "HIIT",  "microburst_balanced",     1.00),
    (r"hiit|hi[_\-]?intensity|interval[_\-]?session", "HIIT", "hiit_unspecified", 0.90),
    (r"vo2[_\-]?max|vo2max",                      "HIIT",  "medium_interval",         0.85),
    (r"5x5|4x4|6x3|long[_\-]?interval",           "HIIT",  "long_interval",           0.95),
    
    # STEADY
    (r"endurance|long[_\-]?ride|z2[_\-]?long",    "STEADY","endurance_z2",            0.90),
    (r"tempo|sub[_\-]?threshold",                 "STEADY","tempo",                   0.90),
    (r"sweet[_\-]?spot|sst",                      "STEADY","sweet_spot",              0.95),
    (r"threshold[_\-]?ride",                      "STEADY","threshold_continuous",    0.85),
    
    # FREE / RACE
    (r"race|criterium|gran[_\-]?fondo|gara",      "FREE",  "race",                    0.95),
    (r"group[_\-]?ride|chaingang|gruppo",         "FREE",  "group_ride",              0.90),
    (r"free[_\-]?ride|recovery[_\-]?ride",        "FREE",  "free_ride",               0.80),
]


def _classify_by_filename(filename: Optional[str]) -> Optional[Tuple[str, str, float]]:
    """
    Strategy A. Returns (category, subtype, confidence) or None if no match.
    
    Matching is case-insensitive and looks at the basename only.
    """
    if not filename:
        return None
    name = Path(filename).stem.lower()
    
    for pattern, cat, sub, conf in _FILENAME_PATTERNS:
        if re.search(pattern, name):
            return (cat, sub, conf)
    
    return None


# =============================================================================
# Strategy B — Lap-structure match
# =============================================================================

def _classify_by_laps(
    laps: List[Dict[str, Any]],
    ftp: Optional[float] = None,
) -> Optional[Tuple[str, str, float, List[str]]]:
    """
    Strategy B. Returns (category, subtype, confidence, notes) or None.
    
    Heuristics:
      - 1 lap covering ~all of the session → not a structured workout. Defer to C.
      - ≥10 laps with regular durations and clear work/rest power alternation
        → HIIT. Sub-classify based on work duration distribution.
      - 3-9 laps with monotonic power increase → TEST (ramp or step test).
      - Few long laps at threshold → TEST (ftp_2x8, ftp_20min, ftp_8min)
      - Single isolated maximal lap → TEST (cp3, cp6, cp12)
    
    Notes are human-readable explanations of the decision.
    """
    if not laps or len(laps) <= 1:
        return None
    
    notes: List[str] = []
    n = len(laps)
    
    # Extract durations and powers
    durs = [l.get("duration_s", 0) for l in laps]
    powers = [l.get("avg_power_w") for l in laps]
    valid_powers = [p for p in powers if p is not None and p > 0]
    
    if not valid_powers:
        notes.append(f"{n} laps but no power data — cannot classify by laps")
        return None
    
    total_dur = sum(durs)
    
    # --- Ramp test signature: monotonically increasing avg power ---
    if 3 <= n <= 30:
        powers_arr = [p for p in powers if p is not None]
        if len(powers_arr) >= 5:
            monotonic_inc = sum(
                1 for i in range(1, len(powers_arr))
                if powers_arr[i] > powers_arr[i-1] + 5
            )
            if monotonic_inc >= 0.7 * (len(powers_arr) - 1):
                notes.append(
                    f"{n} laps with monotonically-increasing power "
                    f"(~{monotonic_inc}/{len(powers_arr)-1} steps up) — ramp test signature"
                )
                return ("TEST", "ramp_test", 0.85, notes)
    
    # --- FTP 2x8 signature: 2-3 long laps at threshold-ish power ---
    if 2 <= n <= 6:
        long_laps = [
            (d, p) for d, p in zip(durs, powers)
            if p is not None and 420 <= d <= 600 and (ftp is None or p >= 0.85 * ftp)
        ]
        if len(long_laps) >= 2 and abs(long_laps[0][1] - long_laps[1][1]) < 0.1 * long_laps[0][1]:
            notes.append(f"{len(long_laps)} threshold-power laps of 7-10min — FTP 2x8 signature")
            return ("TEST", "ftp_2x8", 0.85, notes)
            
    # --- Singolo test CP/MMP da LAP (es. CP3, CP6, CP12 isolato) ---
    if 2 <= n <= 8:
        for d, p in zip(durs, powers):
            # Cerchiamo un lap isolato e marcatamente sopra-soglia
            if p is not None and 150 <= d <= 1500 and (ftp is None or p >= 1.05 * ftp):
                if d < 240: sub = "cp3"
                elif d < 500: sub = "cp6"
                elif d < 900: sub = "cp12"
                else: sub = "ftp_20min"
                
                notes.append(f"Lap isolato massimale di {int(d)}s ad alta intensità ({int(p)}W) — test {sub}")
                return ("TEST", sub, 0.85, notes)
    
    # --- HIIT signature: many short laps with work/rest alternation ---
    if n >= 10:
        # Use the midpoint between min and max as the work/rest separator.
        # This works robustly for bimodal data (HIIT alternating high/low),
        # unlike a median-based threshold which fails on clean 50/50 splits.
        p_min, p_max = min(valid_powers), max(valid_powers)
        threshold = (p_min + p_max) / 2.0
        work_durs = []
        rest_durs = []
        for d, p in zip(durs, powers):
            if p is None:
                continue
            if p > threshold:
                work_durs.append(d)
            else:
                rest_durs.append(d)
        
        if len(work_durs) >= 3 and len(rest_durs) >= 3:
            avg_work = sum(work_durs) / len(work_durs)
            avg_rest = sum(rest_durs) / len(rest_durs)
            ratio = avg_work / avg_rest if avg_rest > 0 else 0
            
            notes.append(
                f"{n} laps, {len(work_durs)} work + {len(rest_durs)} rest, "
                f"avg work={avg_work:.0f}s, avg rest={avg_rest:.0f}s, ratio={ratio:.2f}"
            )
            
            if avg_work < 60:
                if ratio >= 1.5:
                    return ("HIIT", "microburst_high_density", 0.85, notes)
                else:
                    return ("HIIT", "microburst_balanced", 0.85, notes)
            elif avg_work < 180:
                return ("HIIT", "medium_interval", 0.85, notes)
            else:
                if ratio <= 1.5:
                    return ("HIIT", "long_interval", 0.85, notes)
                else:
                    return ("HIIT", "structured_mixed", 0.75, notes)
    
    # --- 5-9 laps with mixed durations: structured mixed ---
    if 5 <= n < 10:
        notes.append(f"{n} laps with mixed structure — likely structured workout")
        return ("HIIT", "structured_mixed", 0.65, notes)
    
    return None


# =============================================================================
# Strategy C — Signal-feature match
# =============================================================================

def _normalized_power(powers: List[float]) -> float:
    """Standard NP: 30s rolling mean → 4th power → mean → 4th root."""
    if not powers or len(powers) < 30:
        return sum(powers) / max(1, len(powers))
    n = len(powers)
    # Rolling 30s mean
    rolling = []
    window_sum = sum(powers[:30])
    rolling.append(window_sum / 30)
    for i in range(30, n):
        window_sum += powers[i] - powers[i-30]
        rolling.append(window_sum / 30)
    if not rolling:
        return 0.0
    # 4th-power mean
    mean_fourth = sum(p**4 for p in rolling) / len(rolling)
    return mean_fourth ** 0.25


def _detect_sustained_blocks(
    powers: List[float],
    ftp: float,
    min_duration_s: int = 120,
    power_floor_frac: float = 0.90,
) -> List[Dict[str, Any]]:
    """
    Find sustained high-power blocks: contiguous stretches at >= power_floor
    of FTP lasting at least min_duration_s, separated by recovery. Used to
    tell a CP/MMP test (few, unequal, maximal blocks) from HIIT (many, equal).

    Returns a list of {start_s, duration_s, mean_w, cv_pct}.
    """
    import numpy as np
    p = np.array(powers, dtype=float)
    n = len(p)
    if n < min_duration_s:
        return []
    floor = power_floor_frac * ftp
    # Smooth lightly to avoid breaking a block on single-second dips.
    k = 15
    if n >= k:
        kernel = np.ones(k) / k
        sm = np.convolve(p, kernel, mode="same")
    else:
        sm = p
    above = sm >= floor
    blocks: List[Dict[str, Any]] = []
    i = 0
    while i < n:
        if above[i]:
            j = i
            while j < n and above[j]:
                j += 1
            dur = j - i
            if dur >= min_duration_s:
                seg = p[i:j]
                seg = seg[seg > 0]
                if len(seg) > 0:
                    m = float(np.mean(seg))
                    cv = 100.0 * float(np.std(seg)) / m if m > 0 else 999.0
                    blocks.append({
                        "start_s": int(i), "duration_s": int(dur),
                        "mean_w": m, "cv_pct": cv,
                    })
            i = j
        else:
            i += 1
    return blocks


def _detect_ramp_protocol(powers: List[float], min_steps: int = 4) -> Dict[str, Any]:
    """
    Rileva matematicamente la presenza di una "funzione a scala" (staircase) nel segnale di potenza.
    Verifica durate fisse, incrementi costanti e stabilità intra-gradino.
    """
    import numpy as np
    p = np.array(powers, dtype=float)
    n = len(p)
    if n < min_steps * 15:
        return {"is_ramp": False, "confidence": 0.0}

    best_ramp = {"is_ramp": False, "confidence": 0.0}
    
    # Durate tipiche dei gradini nei protocolli ciclistici (in secondi)
    # Copre micro-ramps (15s), amatori (30s), standard (60s), e step-test (120s, 180s)
    candidate_durations = [15, 20, 30, 45, 60, 120, 150, 180]

    for d in candidate_durations:
        # 1. Trova il "phase offset" ottimale. 
        # Cerca il punto di inizio che allinea perfettamente la griglia dei gradini,
        # minimizzando la deviazione standard media (varianza intra-blocco).
        best_offset = 0
        min_mean_std = float('inf')

        for offset in range(0, d, 5):  # Scansione a salti di 5s per efficienza
            stds = []
            for i in range(offset, n - d + 1, d):
                stds.append(np.std(p[i:i+d]))
            if stds:
                avg_std = np.mean(stds)
                if avg_std < min_mean_std:
                    min_mean_std = avg_std
                    best_offset = offset

        # 2. Estrai i blocchi allineati usando l'offset ottimale
        steps = []
        for i in range(best_offset, n - d + 1, d):
            block = p[i:i+d]
            steps.append({
                "start": i,
                "mean": float(np.mean(block)),
                "std": float(np.std(block))
            })

        if len(steps) < min_steps:
            continue

        # 3. Cerca la sequenza monotona crescente più lunga (la rampa vera e propria)
        current_streak = []
        longest_streak = []

        for i in range(1, len(steps)):
            prev = steps[i-1]
            curr = steps[i]
            delta = curr["mean"] - prev["mean"]

            # Un gradino è valido se:
            # - L'incremento è tipico di un test (+4W a +60W)
            # - La potenza è sufficientemente stabile. Usiamo una tolleranza del 20% o 15W 
            #   per non penalizzare i test eseguiti su strada o senza ERG mode.
            if 4 <= delta <= 60 and curr["std"] < max(15.0, curr["mean"] * 0.20):
                if not current_streak:
                    current_streak.append(prev)
                current_streak.append(curr)
            else:
                if len(current_streak) > len(longest_streak):
                    longest_streak = current_streak
                current_streak = []

        if len(current_streak) > len(longest_streak):
            longest_streak = current_streak

        # 4. Valuta la regolarità architettonica dei gradini trovati
        if len(longest_streak) >= min_steps:
            deltas = [longest_streak[j]["mean"] - longest_streak[j-1]["mean"] 
                      for j in range(1, len(longest_streak))]
            avg_delta = float(np.mean(deltas))
            cv_delta = float(np.std(deltas)) / avg_delta if avg_delta > 0 else 999.0

            # Se il delta CV è < 40%, significa che gli incrementi sono molto regolari 
            # (es. salti da 23W, 26W, 25W, 24W per un target di 25W)
            if cv_delta < 0.45:
                # La confidenza sale all'aumentare dei gradini e della loro regolarità (basso CV)
                conf = min(0.99, 0.60 + (len(longest_streak) * 0.04) - (cv_delta * 0.6))
                
                if conf > best_ramp["confidence"]:
                    best_ramp = {
                        "is_ramp": True,
                        "step_duration": d,
                        "step_increment": round(avg_delta, 1),
                        "n_steps": len(longest_streak),
                        "confidence": round(conf, 3),
                        "delta_cv": round(cv_delta, 3)
                    }

    return best_ramp


def _classify_by_signal(
    powers: List[float],
    ftp: Optional[float] = None,
) -> Tuple[str, str, float, List[str]]:
    """
    Strategy C (always returns something — last resort).
    
    Decision tree from signal features:
      - Long monotonic ramp → ramp_test
      - Very short, single peak >150% FTP, rest at Z1 → single_sprint
      - High variability + peaks → FREE/race
      - Low variability + threshold-ish power → STEADY/tempo or threshold
      - Mixed → HIIT/unspecified
    """
    notes: List[str] = []
    n = len(powers)
    if n < 30:
        notes.append(f"only {n} samples — too short to classify reliably")
        return ("UNCLASSIFIED", "unknown", 0.10, notes)
    
    avg = sum(powers) / n
    np_ = _normalized_power(powers)
    vi = np_ / avg if avg > 0 else 0
    if_ = np_ / ftp if ftp else 0
    
    # Time-in-zone analysis (only meaningful with FTP)
    pct_above_ftp = pct_below_50 = pct_above_150 = 0.0
    if ftp:
        pct_above_ftp = sum(1 for p in powers if p > ftp) / n
        pct_below_50 = sum(1 for p in powers if p < 0.5 * ftp) / n
        pct_above_150 = sum(1 for p in powers if p > 1.5 * ftp) / n
    
    # Spike detection: very-high power events
    n_spikes = 0
    in_spike = False
    spike_thr = 1.5 * ftp if ftp else 500
    for p in powers:
        if p > spike_thr and not in_spike:
            n_spikes += 1
            in_spike = True
        elif p < spike_thr * 0.6:
            in_spike = False
            
    # --- CP / MMP test signature ---
    if ftp and n >= 360:
        blocks = _detect_sustained_blocks(powers, ftp)
        
        # 1. Test MMP Multiplo
        if 2 <= len(blocks) <= 4:
            durs_b = sorted(b["duration_s"] for b in blocks)
            dur_spread = (durs_b[-1] / durs_b[0]) if durs_b[0] > 0 else 1.0
            all_long = all(b["duration_s"] >= 120 for b in blocks)
            all_steady = all(b["cv_pct"] <= 10.0 for b in blocks)
            if all_long and all_steady and dur_spread >= 1.4:
                notes.append(
                    f"{len(blocks)} sustained blocks of different durations "
                    f"({'/'.join(f'{int(d)}s' for d in durs_b)}) — CP/MMP test"
                )
                return ("TEST", "cp_test", 0.80, notes)
                
        # 2. Test CP Singolo Isolato
        elif len(blocks) == 1:
            b = blocks[0]
            d = b["duration_s"]
            # Richiede potenza molto alta (>105% FTP) e basso coefficiente di variazione
            if 150 <= d <= 1500 and b["mean_w"] >= 1.05 * ftp and b["cv_pct"] <= 12.0:
                if d < 240: sub = "cp3"
                elif d < 500: sub = "cp6"
                elif d < 900: sub = "cp12"
                else: sub = "ftp_20min"
                notes.append(f"Singolo sforzo massimale sostenuto di {int(d)}s (CV={b['cv_pct']:.1f}%) — test {sub} isolato.")
                return ("TEST", sub, 0.75, notes)

    # --- Structured Ramp Test signature ---
    # Rilevamento basato sull'architettura a gradini (durata, delta P, stabilità)
    ramp_info = _detect_ramp_protocol(powers)
    if ramp_info["is_ramp"] and ramp_info["confidence"] > 0.65:
        notes.append(
            f"Rilevata struttura Ramp/Step Test: {ramp_info['n_steps']} gradini continui da "
            f"{ramp_info['step_duration']}s, incremento medio +{ramp_info['step_increment']}W "
            f"(regolarità incrementi CV={ramp_info['delta_cv']*100:.0f}%)."
        )
        return ("TEST", "ramp_test", ramp_info["confidence"], notes)
    
    # --- Mixed test signature: sprint(s) + continuous high-power block
    # Recognize the flow_protocol pattern: 1+ very-high spikes + ≥5 min
    # block at near-threshold power. Common in test sessions that combine
    # sprint anchor with CP anchor (e.g., sprint + cp12). ---
    if ftp and n >= 1800:
        # Detect isolated very-high peaks (>3x FTP, typical sprint test power)
        very_high_peaks = sum(1 for p in powers if p > 3.0 * ftp)
        # Detect a continuous high-power block (3 min rolling mean ≥ 95% FTP)
        long_high_block = False
        if n >= 180:
            window = 180
            ws = sum(powers[:window])
            target = 0.95 * ftp
            if ws / window >= target:
                long_high_block = True
            for i in range(window, n):
                ws += powers[i] - powers[i-window]
                if ws / window >= target:
                    long_high_block = True
                    break
        
        if very_high_peaks >= 5 and long_high_block:
            return ("TEST", "mixed_test", 0.60, [
                f"{very_high_peaks} samples >3×FTP (sprint anchor) + "
                f"≥3min sustained at ≥95% FTP (CP anchor) — mixed test pattern"])
    
    # --- Sprint set / sprint test: characteristic isolated peaks
    # Sprint tests often have multiple sprints at the END preceded by
    # a long warmup. So the global pct_below_50 may not be high, but
    # the temporal density of spikes matters. ---
    if ftp and n_spikes >= 2:
        # Count spikes that are temporally clustered (within 5 min of each other)
        # AND are very high (>3x FTP — true sprint efforts, not just hard pedaling)
        sprint_efforts = sum(1 for p in powers if p > 3.0 * ftp)
        if sprint_efforts >= 5 and n_spikes <= 8:
            return ("TEST", "sprint_set", 0.55, [
                f"{n_spikes} isolated spikes >150% FTP "
                f"({sprint_efforts} samples >3×FTP) — sprint set test"])
    
    # --- Sprint set: multiple isolated peaks with mostly low power (lenient) ---
    if 2 <= n_spikes <= 8 and ftp:
        time_low = sum(1 for p in powers if p < 0.6 * ftp) / n
        if time_low > 0.45 and n_spikes >= 2:
            return ("TEST", "sprint_set", 0.55, [
                f"{n_spikes} isolated spikes >150% FTP, {time_low*100:.0f}% "
                f"time below 60% FTP — sprint set test signature"])
    
    # --- Single sprint test: 1-2 spikes in short session with mostly easy power ---
    # Looser thresholds to catch warmup+sprint sessions
    if 1 <= n_spikes <= 2 and ftp:
        time_easy = sum(1 for p in powers if p < 0.6 * ftp) / n
        if time_easy > 0.55 and n < 2400:  # ≤40min, mostly easy + a couple sprints
            notes.append(
                f"{n_spikes} spike(s) above 150% FTP, {time_easy*100:.0f}% "
                f"time below 60% FTP in a {n/60:.0f}min session — single sprint test"
            )
            return ("TEST", "single_sprint", 0.55, notes)
    
    # --- Multiple sprints: keep the older path for backward compat ---
    if n_spikes >= 3 and pct_below_50 > 0.5 and n < 3600:
        notes.append(f"{n_spikes} spikes above 150% FTP with mostly easy ride — sprint set")
        return ("TEST", "sprint_set", 0.50, notes)
    
    # --- Low variability + at-threshold = STEADY ---
    if vi < 1.10 and ftp and 0.75 <= if_ <= 1.05:
        if if_ >= 0.95:
            return ("STEADY", "threshold_continuous", 0.50, [
                f"IF={if_:.2f}, VI={vi:.2f} — threshold-continuous signature"])
        elif if_ >= 0.85:
            return ("STEADY", "sweet_spot", 0.50, [
                f"IF={if_:.2f}, VI={vi:.2f} — sweet-spot signature"])
        else:
            return ("STEADY", "tempo", 0.50, [
                f"IF={if_:.2f}, VI={vi:.2f} — tempo signature"])
    
    # --- Endurance: low IF, long, low spikes ---
    if ftp and if_ < 0.70 and n > 1800 and n_spikes < 5:
        return ("STEADY", "endurance_z2", 0.55, [
            f"IF={if_:.2f}, {n/60:.0f}min, only {n_spikes} spikes — endurance Z2"])
    
    # --- High variability, multiple spikes, long → race / free ---
    if vi > 1.20 and n_spikes >= 3:
        return ("FREE", "race", 0.45, [
            f"VI={vi:.2f}, {n_spikes} spikes — race/group-ride signature"])
    
    # --- Otherwise, HIIT-ish ---
    if ftp and pct_above_ftp > 0.15:
        return ("HIIT", "hiit_unspecified", 0.45, [
            f"{pct_above_ftp*100:.0f}% time above FTP, VI={vi:.2f} — generic HIIT"])
    
    # Last resort
    notes.append(f"no clear signature: VI={vi:.2f}, IF={if_:.2f}")
    return ("UNCLASSIFIED", "unknown", 0.30, notes)


# =============================================================================
# Anchor extraction (for TEST sessions)
# =============================================================================

# Map subtype → durations whose max-mean-power constitutes a qualified anchor
_ANCHOR_DURATIONS: Dict[str, List[int]] = {
    "ramp_test":     [60, 180, 300],   # the last ~5 min of the ramp = MAP
    "ftp_2x8":       [480],            # 8 min
    "ftp_20min":     [1200],           # 20 min
    "ftp_8min":      [480],            # 8 min
    "cp3":           [180],            # 3 min
    "cp6":           [360],            # 6 min
    "cp12":          [720],            # 12 min
    "single_sprint": [5, 15],          # 5s and 15s
    "sprint_set":    [5, 15, 30],      # multiple sprint durations
    "mixed_test":    [5, 15, 30, 180, 360, 720],  # combined → multiple anchors
}


def _extract_qualified_anchors(
    powers: List[float],
    subtype: str,
) -> List[QualifiedAnchor]:
    """
    For a TEST session, extract the MMP anchor(s) the test was designed to
    produce. Each anchor gets reliability=1.0 because the test by design
    targets that duration.
    """
    if subtype not in _ANCHOR_DURATIONS:
        return []
    
    durations = _ANCHOR_DURATIONS[subtype]
    n = len(powers)
    anchors = []
    
    for d in durations:
        if d > n:
            continue  # not enough data
        # Rolling mean over duration d, find the max
        window_sum = sum(powers[:d])
        max_val = window_sum / d
        for i in range(d, n):
            window_sum += powers[i] - powers[i-d]
            avg = window_sum / d
            if avg > max_val:
                max_val = avg
        
        if max_val <= 0:
            continue
        
        anchors.append(QualifiedAnchor(
            duration_s=d,
            power_w=round(max_val, 1),
            anchor_reliability=1.0,
            source_subtype=subtype,
            notes=f"Max-mean-power over {d}s within a {subtype} session",
        ))
    
    return anchors


# =============================================================================
# Stimulus vector (time-in-zone)
# =============================================================================

def _compute_stimulus_vector(
    powers: List[float],
    ftp: Optional[float],
) -> Optional[StimulusVector]:
    """
    Compute time-in-zone for the standard physiological zones, given FTP.
    Returns None if FTP is not known.
    
    Zones (relative to FTP):
      <75%:    aerobic_base
      75-90%:  tempo
      90-105%: threshold
      105-120%: vo2max
      120-150%: anaerobic
      >150%:   neuromuscular
    """
    if not ftp or ftp <= 0:
        return None
    
    sv = StimulusVector(total_time_s=len(powers))
    for p in powers:
        if p <= 0:
            continue
        pct = p / ftp
        if pct < 0.75:
            sv.aerobic_base_stimulus_s += 1
        elif pct < 0.90:
            sv.tempo_stimulus_s += 1
        elif pct < 1.05:
            sv.threshold_stimulus_s += 1
        elif pct < 1.20:
            sv.vo2max_stimulus_s += 1
        elif pct < 1.50:
            sv.anaerobic_stimulus_s += 1
        else:
            sv.neuromuscular_stimulus_s += 1
    
    return sv


# =============================================================================
# Public API
# =============================================================================

def classify_session(
    powers: List[float],
    *,
    filename: Optional[str] = None,
    laps: Optional[List[Dict[str, Any]]] = None,
    ftp: Optional[float] = None,
    hint: Optional[Tuple[str, str]] = None,
) -> ClassifiedSession:
    """
    Classify a workout session.
    
    Parameters
    ----------
    powers : list of float
        1Hz power stream in watts. Zeros are treated as recovery / coasting.
    filename : str, optional
        Original FIT filename (basename or full path). Used by Strategy A.
    laps : list of dict, optional
        Lap structure: [{duration_s, avg_power_w, max_power_w, ...}].
        Used by Strategy B.
    ftp : float, optional
        Functional Threshold Power. Required for stimulus vector and for
        some signal-feature decisions in Strategy C.
    hint : (category, subtype), optional
        Manual override from the user/app. If supplied, bypasses all
        strategies and uses these values with confidence=1.0 and
        source="hint".
    
    Returns
    -------
    ClassifiedSession with all populated fields.
    """
    # Diagnostic stats (always computed)
    n = len(powers)
    avg = sum(powers) / n if n else 0
    np_ = _normalized_power(powers)
    vi = np_ / avg if avg > 0 else 0
    if_ = np_ / ftp if ftp else 0
    
    # Manual hint takes precedence
    if hint:
        cat, sub = hint
        result = ClassifiedSession(
            category=cat, subtype=sub, confidence=1.0, source="hint",
            notes=[f"User/app provided explicit hint: category={cat}, subtype={sub}"],
            duration_s=n, avg_power_w=avg, normalized_power_w=np_,
            variability_index=vi, intensity_factor=if_,
        )
    else:
        # Strategy A — filename
        a_res = _classify_by_filename(filename)
        if a_res is not None:
            cat, sub, conf = a_res
            result = ClassifiedSession(
                category=cat, subtype=sub, confidence=conf, source="filename",
                notes=[f"Filename '{filename}' matched a known pattern"],
                duration_s=n, avg_power_w=avg, normalized_power_w=np_,
                variability_index=vi, intensity_factor=if_,
            )
        else:
            # Strategy B — laps
            b_res = _classify_by_laps(laps or [], ftp=ftp)
            if b_res is not None:
                cat, sub, conf, b_notes = b_res
                result = ClassifiedSession(
                    category=cat, subtype=sub, confidence=conf, source="laps",
                    notes=b_notes,
                    duration_s=n, avg_power_w=avg, normalized_power_w=np_,
                    variability_index=vi, intensity_factor=if_,
                )
            else:
                # Strategy C — signal features (always returns something)
                cat, sub, conf, c_notes = _classify_by_signal(powers, ftp=ftp)
                result = ClassifiedSession(
                    category=cat, subtype=sub, confidence=conf, source="signal",
                    notes=c_notes,
                    duration_s=n, avg_power_w=avg, normalized_power_w=np_,
                    variability_index=vi, intensity_factor=if_,
                )
    
    # Extract qualified anchors if this is a TEST
    if result.category == "TEST":
        result.qualified_anchors = _extract_qualified_anchors(powers, result.subtype)
    
    # Compute stimulus vector (independent of classification)
    result.stimulus_vector = _compute_stimulus_vector(powers, ftp)
    
    return result


# =============================================================================
# Protocol Completeness — onboarding planner
# =============================================================================
#
# Given an athlete's current MMP coverage (from past activities), report:
#   - Which physiological windows are covered
#   - Which TEST subtypes would fill the missing windows
#   - Expected confidence improvement after each test
#
# This is the "onboarding protocol planner" that the PDF documents.

# Map: TEST subtype → which expressiveness windows it covers
# The windows match ExpressivenessReport in metabolic_profiler.py:
#   neuromuscular: 5-15s
#   glycolytic:    20-60s
#   vo2max:        180-480s
#   threshold:     1200-3600s
_TEST_FILLS_WINDOWS: Dict[str, List[str]] = {
    "sprint_test":    ["neuromuscular"],
    "single_sprint":  ["neuromuscular"],
    "sprint_set":     ["neuromuscular", "glycolytic"],
    "cp3":            ["vo2max"],     # 180s falls in 180-720s
    "cp6":            ["vo2max"],     # 360s
    "cp12":           ["vo2max"],     # 720s (extended boundary)
    "ftp_8min":       ["vo2max"],     # 480s
    "ftp_2x8":        ["vo2max"],     # 480s (was incorrectly listed as threshold)
    "ftp_20min":      ["threshold"],  # 1200s — actually fills MLSS region
    "ramp_test":      ["vo2max"],
    "mixed_test":     ["neuromuscular", "glycolytic", "vo2max", "threshold"],
}

# Human-readable test descriptions
_TEST_DESCRIPTIONS: Dict[str, Dict[str, Any]] = {
    "sprint_set": {
        "title": "Sprint Set",
        "duration_min": 45,
        "setting": "trainer indoor (preferito) o pista chiusa",
        "phases": [
            ("Warm-up Z2 progressivo", "15 min"),
            ("4× sprint 5s all-out, recovery 5min Z1", "21 min"),
            ("2× 15s all-out, recovery 5min Z1", "12 min"),
            ("2× 30s all-out, recovery 8min Z1", "18 min"),
            ("2× 60s all-out sostenibile, recovery 10min Z1", "22 min"),
            ("Cooldown Z1", "10 min"),
        ],
        "fills": ["neuromuscular", "glycolytic"],
        "anchors_produced": "5s, 15s, 30s, 60s",
        "notes": "Recupero pieno tra ripetizioni; non eseguire dopo workout intenso (TSB < -10).",
    },
    "ramp_test": {
        "title": "Ramp Test",
        "duration_min": 30,
        "setting": "trainer indoor",
        "phases": [
            ("Warm-up Z2 progressivo", "15 min"),
            ("Ramp: +25W ogni 1 min da 100W ad esaurimento", "20-30 min"),
            ("Cooldown Z1", "10 min"),
        ],
        "fills": ["vo2max"],
        "anchors_produced": "peak ramp (3-5 min ai watt più alti)",
        "notes": "Incremento +25W/min fitta meglio i parametri Mader rispetto a step più rapidi.",
    },
    "cp6": {
        "title": "CP6 — 6 min all-out",
        "duration_min": 45,
        "setting": "trainer o strada (piatta, no vento)",
        "phases": [
            ("Warm-up 20 min con 2× allungo 1min", "20 min"),
            ("Recupero 5 min Z1", "5 min"),
            ("6 min all-out sostenibile (pacing: 1' controllato + 5' progressivo)", "6 min"),
            ("Cooldown 10 min Z1", "10 min"),
        ],
        "fills": ["vo2max"],
        "anchors_produced": "360s",
        "notes": "Alternativa al ramp test; produce un anchor 360s diretto.",
    },
    "cp12": {
        "title": "CP12 — 12 min all-out",
        "duration_min": 50,
        "setting": "trainer o strada (piatta)",
        "phases": [
            ("Warm-up 20 min", "20 min"),
            ("Recupero 5 min Z1", "5 min"),
            ("12 min all-out (pacing: 2' controllato + 10' progressivo)", "12 min"),
            ("Cooldown 10 min Z1", "10 min"),
        ],
        "fills": ["threshold"],
        "anchors_produced": "720s",
        "notes": "Produce anchor 12min usato per stimare MLSS.",
    },
    "ftp_2x8": {
        "title": "FTP 2×8 Test",
        "duration_min": 60,
        "setting": "trainer indoor (preferito per controllo)",
        "phases": [
            ("Warm-up 15 min", "15 min"),
            ("8 min all-out sostenibile", "8 min"),
            ("Recovery 10 min Z1", "10 min"),
            ("8 min all-out sostenibile", "8 min"),
            ("Cooldown 10 min", "10 min"),
        ],
        "fills": ["threshold"],
        "anchors_produced": "480s × 2 (si usa il migliore)",
        "notes": "Test FTP classico (Coggan 2×8min). Alternativa al ftp_20min.",
    },
    "mixed_test": {
        "title": "Mixed Test (Flow Protocol)",
        "duration_min": 60,
        "setting": "trainer indoor",
        "phases": [
            ("Warm-up 15 min", "15 min"),
            ("Sprint set: 3× 15s all-out con 5min recovery", "20 min"),
            ("Recovery 10 min Z1", "10 min"),
            ("CP12: 12 min all-out", "12 min"),
            ("Cooldown 10 min", "10 min"),
        ],
        "fills": ["neuromuscular", "glycolytic", "vo2max"],
        "anchors_produced": "5s, 15s, 30s, 720s",
        "notes": "Combina sprint anchor + cp12 anchor in una sessione. NON copre la finestra threshold (>20min); per quella serve ftp_20min separato.",
    },
    "ftp_20min": {
        "title": "FTP 20-min Test",
        "duration_min": 60,
        "setting": "strada piatta (preferito) o trainer",
        "phases": [
            ("Warm-up 20 min con 2× 1min @ 90% FTP", "20 min"),
            ("Recovery 5 min Z1", "5 min"),
            ("20 min all-out sostenibile", "20 min"),
            ("Cooldown 15 min", "15 min"),
        ],
        "fills": ["threshold"],
        "anchors_produced": "1200s (FTP = 95% del 20-min)",
        "notes": "Test FTP classico. Anchor 1200s usato direttamente per stimare MLSS.",
    },
}


@dataclass
class ProtocolStep:
    """One recommended test in the onboarding plan."""
    test_subtype: str
    title: str
    duration_min: int
    fills_windows: List[str]      # which expressiveness windows it covers
    rationale: str                # why this test is suggested next
    priority: int                  # 1 = highest (do first)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_subtype": self.test_subtype,
            "title": self.title,
            "duration_min": self.duration_min,
            "fills_windows": self.fills_windows,
            "rationale": self.rationale,
            "priority": self.priority,
        }


@dataclass
class ProtocolCompletenessReport:
    """
    Status of an athlete's anchor coverage and a plan to complete it.
    """
    covered_windows: List[str]
    missing_windows: List[str]
    completeness_pct: int                  # 0-100
    expected_current_confidence: str       # "very_low" | "low" | "fair" | "high"
    expected_post_protocol_confidence: str
    recommended_tests: List[ProtocolStep]
    n_qualified_anchors: int
    total_duration_min_to_complete: int
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "covered_windows": self.covered_windows,
            "missing_windows": self.missing_windows,
            "completeness_pct": self.completeness_pct,
            "expected_current_confidence": self.expected_current_confidence,
            "expected_post_protocol_confidence": self.expected_post_protocol_confidence,
            "recommended_tests": [s.to_dict() for s in self.recommended_tests],
            "n_qualified_anchors": self.n_qualified_anchors,
            "total_duration_min_to_complete": self.total_duration_min_to_complete,
            "tier": "HEURISTIC",  # recommendations are coach-facing guidance
        }


def protocol_completeness(
    qualified_anchors: Optional[List["QualifiedAnchor"]] = None,
    available_durations_s: Optional[List[int]] = None,
) -> ProtocolCompletenessReport:
    """
    Plan the onboarding tests an athlete needs to reach full expressiveness.
    
    Pass either:
      - `qualified_anchors`: a list of QualifiedAnchor (from classify_session
        on past TEST sessions). These count fully (reliability=1.0).
      - `available_durations_s`: just a list of MMP durations available.
        Less precise (they might come from rolling windows), but fallback
        when no classified anchors exist.
    
    Returns a ProtocolCompletenessReport with:
      - Which windows are already covered
      - Which are still missing
      - Recommended tests in priority order
      - Estimated total time to complete the protocol
    
    This is what the PDF onboarding protocol documents in human-readable
    form — this function is the programmatic equivalent.
    """
    durations: set = set()
    
    if qualified_anchors:
        for a in qualified_anchors:
            durations.add(a.duration_s)
    if available_durations_s:
        durations.update(available_durations_s)
    
    # Determine coverage by window. These must match
    # metabolic_profiler.ExpressivenessReport so the two analyses agree.
    has_neuro = any(5 <= d <= 15 for d in durations)
    has_glyco = any(20 <= d <= 60 for d in durations)
    has_vo2   = any(180 <= d <= 720 for d in durations)   # extended to 720s
    has_thr   = any(1200 <= d <= 3600 for d in durations)
    
    covered = []
    if has_neuro: covered.append("neuromuscular")
    if has_glyco: covered.append("glycolytic")
    if has_vo2:   covered.append("vo2max")
    if has_thr:   covered.append("threshold")
    
    missing = [w for w in ("neuromuscular", "glycolytic", "vo2max", "threshold")
               if w not in covered]
    
    completeness_pct = round(100 * len(covered) / 4)
    
    # Expected confidence based on coverage
    if completeness_pct == 100:
        post_conf = "high"
        current_conf = "high"
    elif completeness_pct >= 75:
        post_conf = "high"
        current_conf = "fair"
    elif completeness_pct >= 50:
        post_conf = "high"
        current_conf = "low"
    else:
        post_conf = "high"
        current_conf = "very_low"
    
    # Build recommended tests to fill missing windows
    # Strategy: prefer mixed_test if 3+ windows missing (efficient single session)
    # otherwise pick single-purpose tests
    recommendations: List[ProtocolStep] = []
    
    if len(missing) >= 3:
        # Suggest mixed_test as first priority — covers multiple windows
        td = _TEST_DESCRIPTIONS["mixed_test"]
        relevant_fills = [w for w in td["fills"] if w in missing]
        recommendations.append(ProtocolStep(
            test_subtype="mixed_test",
            title=td["title"],
            duration_min=td["duration_min"],
            fills_windows=relevant_fills,
            rationale=(
                f"Sessione combinata che copre {len(relevant_fills)} finestre "
                f"({', '.join(relevant_fills)}) in {td['duration_min']} minuti."
            ),
            priority=1,
        ))
        # Track which windows we'll still need after mixed_test
        still_missing = [w for w in missing if w not in td["fills"]]
    else:
        still_missing = list(missing)
    
    # For remaining missing windows, suggest specific tests
    priority = len(recommendations) + 1
    suggested_by_window = {
        "neuromuscular": "sprint_set",
        "glycolytic":    "sprint_set",
        "vo2max":        "cp6",
        "threshold":     "ftp_20min",
    }
    
    suggested_set = set()
    for window in still_missing:
        test = suggested_by_window.get(window)
        if test and test not in suggested_set:
            td = _TEST_DESCRIPTIONS.get(test, {})
            if td:
                fills_relevant = [w for w in td["fills"] if w in still_missing]
                recommendations.append(ProtocolStep(
                    test_subtype=test,
                    title=td.get("title", test),
                    duration_min=td.get("duration_min", 45),
                    fills_windows=fills_relevant,
                    rationale=(
                        f"Riempie la finestra '{window}' "
                        f"({td.get('anchors_produced', '?')})."
                    ),
                    priority=priority,
                ))
                priority += 1
                suggested_set.add(test)
    
    total_dur = sum(r.duration_min for r in recommendations)
    
    return ProtocolCompletenessReport(
        covered_windows=covered,
        missing_windows=missing,
        completeness_pct=completeness_pct,
        expected_current_confidence=current_conf,
        expected_post_protocol_confidence=post_conf,
        recommended_tests=recommendations,
        n_qualified_anchors=len([a for a in (qualified_anchors or [])]),
        total_duration_min_to_complete=total_dur,
    )