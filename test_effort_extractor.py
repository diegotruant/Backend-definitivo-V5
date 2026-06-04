"""
Test-effort extractor.
=======================

Turns one or more FIT files into a *proposed* physiological profile, the
strong anchor used by athlete_physiological_prior.MeasuredProfile.

The backend is autonomous but not silent: it scans every file, finds the
maximal efforts that look like test trials (an all-out sprint and the
constant-power CP blocks of a Flow-style protocol), scores how confident it
is, and returns a PROPOSAL. The coach confirms or rejects before anything
becomes the athlete's anchor. Nothing here writes a MeasuredProfile directly.

Effort detection uses two independent signals and merges them:
  * Laps  — if the rider pressed the lap button to mark trials, those bounds
            are trusted (high confidence).
  * Power — a lap-free scan that finds the sprint (a brief peak that then
            collapses) and the steady CP plateaus (low-variability blocks
            near the athlete's best for that duration).
Both run always; laps refine, power is the fallback. Files arrive in any mix
(test + normal rides), so each candidate is judged on its own merits.

The extractor does not decide alone which file is "the test": it proposes,
flags confidence, and leaves confirmation to the caller.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Candidate efforts
# ---------------------------------------------------------------------------
@dataclass
class SprintCandidate:
    file_id: str
    start_s: int
    peak_1s_w: float
    mean_w: float
    duration_s: int
    source: str               # "lap" | "power"
    sustain_ratio: float      # mean / peak — how all-out it is
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_id": self.file_id, "start_s": self.start_s,
            "peak_1s_w": round(self.peak_1s_w, 0), "mean_w": round(self.mean_w, 0),
            "duration_s": self.duration_s, "source": self.source,
            "sustain_ratio": round(self.sustain_ratio, 3), "notes": self.notes,
        }


@dataclass
class CPCandidate:
    file_id: str
    start_s: int
    duration_s: int
    mean_w: float
    cv_pct: float             # coefficient of variation of power (lower = steadier)
    target_label: str         # "cp3" | "cp6" | "cp12"
    source: str               # "lap" | "power"
    maximality: float         # 0..1, mean_w vs athlete best for this duration
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_id": self.file_id, "start_s": self.start_s,
            "duration_s": self.duration_s, "mean_w": round(self.mean_w, 0),
            "cv_pct": round(self.cv_pct, 1), "target_label": self.target_label,
            "source": self.source, "maximality": round(self.maximality, 2),
            "notes": self.notes,
        }


@dataclass
class ProfileProposal:
    """A proposed measured profile awaiting coach confirmation."""
    status: str                                   # "proposed" | "incomplete" | "empty"
    sprint: Optional[SprintCandidate] = None
    cp_candidates: List[CPCandidate] = field(default_factory=list)
    mmp_for_fit: Dict[int, float] = field(default_factory=dict)
    confidence: float = 0.0
    warnings: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "sprint": self.sprint.to_dict() if self.sprint else None,
            "cp_candidates": [c.to_dict() for c in self.cp_candidates],
            "mmp_for_fit": {int(k): round(v, 1) for k, v in self.mmp_for_fit.items()},
            "confidence": round(self.confidence, 3),
            "warnings": self.warnings,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Target CP windows (Flow-style protocol: MMP3 / MMP6 / MMP12)
# ---------------------------------------------------------------------------
_CP_TARGETS = [
    ("cp3", 180, 150, 240),    # label, nominal_s, min_s, max_s
    ("cp6", 360, 300, 450),
    ("cp12", 720, 600, 900),
]


def _clean_power(power: List[Optional[float]]) -> np.ndarray:
    return np.nan_to_num(np.array([p if p is not None else 0.0 for p in power], dtype=float), nan=0.0)


def _best_mean(power: np.ndarray, w: int) -> float:
    if len(power) < w:
        return 0.0
    return float(np.max(np.convolve(power, np.ones(w) / w, mode="valid")))


# ---------------------------------------------------------------------------
# Sprint detection
# ---------------------------------------------------------------------------
def _find_sprint_in_power(power: np.ndarray, file_id: str) -> Optional[SprintCandidate]:
    """
    A test sprint is a brief, very high effort that then collapses. We find the
    global short-window peak and measure how long power stays near-maximal
    before dropping, giving the *actual* sprint duration rather than a fixed
    window (a real all-out sprint fades after ~10-20 s).
    """
    if len(power) < 5 or float(np.max(power)) < 400.0:
        return None
    # 1 s peak and its location
    peak_idx = int(np.argmax(power))
    peak_1s = float(power[peak_idx])
    # Walk forward from the onset to find where power falls below ~55% of peak
    # (sprint collapse). Onset = a few seconds before the peak.
    onset = peak_idx
    while onset > 0 and power[onset - 1] > 0.35 * peak_1s:
        onset -= 1
    end = peak_idx
    while end < len(power) - 1 and power[end + 1] > 0.55 * peak_1s:
        end += 1
    dur = max(1, end - onset + 1)
    if dur < 5 or dur > 40:           # not a sprint-shaped effort
        return None
    seg = power[onset:end + 1]
    mean_w = float(np.mean(seg))
    return SprintCandidate(
        file_id=file_id, start_s=onset, peak_1s_w=peak_1s, mean_w=mean_w,
        duration_s=dur, source="power", sustain_ratio=mean_w / peak_1s,
        notes=f"power-scan sprint, {dur}s near-maximal",
    )


def _find_sprint_in_laps(power: np.ndarray, laps: List[Dict[str, Any]], file_id: str) -> Optional[SprintCandidate]:
    """A lap of 10-30 s with a high peak is a marked sprint trial."""
    t = 0
    best: Optional[SprintCandidate] = None
    for lap in laps:
        d = int(lap.get("duration_s", 0))
        if d <= 0:
            continue
        seg = power[t:t + d]
        t += d
        if not (10 <= d <= 30) or len(seg) == 0:
            continue
        peak = float(np.max(seg))
        if peak < 400.0:
            continue
        mean_w = float(np.mean(seg))
        cand = SprintCandidate(
            file_id=file_id, start_s=t - d, peak_1s_w=peak, mean_w=mean_w,
            duration_s=d, source="lap", sustain_ratio=mean_w / peak,
            notes=f"lap-marked sprint trial ({d}s)",
        )
        if best is None or cand.mean_w > best.mean_w:
            best = cand
    return best


# ---------------------------------------------------------------------------
# CP plateau detection
# ---------------------------------------------------------------------------
def _cv_pct(seg: np.ndarray) -> float:
    m = float(np.mean(seg))
    if m <= 0:
        return 999.0
    return 100.0 * float(np.std(seg)) / m


def _find_cp_in_laps(power: np.ndarray, laps: List[Dict[str, Any]], file_id: str) -> List[CPCandidate]:
    out: List[CPCandidate] = []
    t = 0
    for lap in laps:
        d = int(lap.get("duration_s", 0))
        if d <= 0:
            continue
        seg = power[t:t + d]
        t += d
        if len(seg) == 0:
            continue
        for label, nominal, lo, hi in _CP_TARGETS:
            if lo <= d <= hi:
                mean_w = float(np.mean(seg))
                if mean_w < 100.0:
                    continue
                out.append(CPCandidate(
                    file_id=file_id, start_s=t - d, duration_s=d, mean_w=mean_w,
                    cv_pct=_cv_pct(seg), target_label=label, source="lap",
                    maximality=0.0,  # filled later vs athlete best
                    notes=f"lap-marked {label} ({d}s)",
                ))
                break
    return out


def _find_cp_in_power(power: np.ndarray, file_id: str) -> List[CPCandidate]:
    """
    For each target window, take the best continuous mean-power block and
    accept it as a CP candidate only if it is steady (low CV) — a true maximal
    constant effort, not a variable race segment.
    """
    out: List[CPCandidate] = []
    for label, nominal, lo, hi in _CP_TARGETS:
        w = nominal
        if len(power) < w:
            continue
        conv = np.convolve(power, np.ones(w) / w, mode="valid")
        idx = int(np.argmax(conv))
        seg = power[idx:idx + w]
        mean_w = float(np.mean(seg))
        if mean_w < 100.0:
            continue
        cv = _cv_pct(seg)
        # Steady-effort gate: a maximal constant CP test holds CV under ~8%.
        # Variable race/ride segments are noisier and are not accepted here
        # (they can still feed the rolling MMP elsewhere, just not as a test).
        if cv > 8.0:
            continue
        out.append(CPCandidate(
            file_id=file_id, start_s=idx, duration_s=w, mean_w=mean_w,
            cv_pct=cv, target_label=label, source="power",
            maximality=0.0,
            notes=f"power-scan {label}, CV {cv:.1f}%",
        ))
    return out


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def extract_test_proposal(
    files: List[Dict[str, Any]],
) -> ProfileProposal:
    """
    Scan FIT-derived data and propose a measured profile for coach review.

    Parameters
    ----------
    files : list of dict, one per FIT file:
        {
          "file_id": str,
          "power":   list[float|None],   # 1 Hz power stream
          "laps":    list[dict] | None,  # optional [{duration_s, avg_power_w}, ...]
        }

    Returns
    -------
    ProfileProposal — candidates + confidence + warnings, awaiting confirmation.
    Never writes an anchor; the caller decides.
    """
    proposal = ProfileProposal(status="empty")
    if not files:
        proposal.warnings.append("No files provided.")
        return proposal

    all_sprints: List[SprintCandidate] = []
    all_cps: List[CPCandidate] = []
    # Athlete best per duration across ALL files — used to score CP maximality.
    athlete_best: Dict[int, float] = {}

    for f in files:
        fid = f.get("file_id", "unknown")
        power = _clean_power(f.get("power", []))
        laps = f.get("laps") or []
        if len(power) == 0:
            continue

        for label, nominal, lo, hi in _CP_TARGETS:
            athlete_best[nominal] = max(athlete_best.get(nominal, 0.0), _best_mean(power, nominal))

        # Sprint: prefer a lap-marked one, else power scan.
        sprint = _find_sprint_in_laps(power, laps, fid) if laps else None
        if sprint is None:
            sprint = _find_sprint_in_power(power, fid)
        if sprint is not None:
            all_sprints.append(sprint)

        # CP: laps first, then fill missing targets from the power scan.
        cps = _find_cp_in_laps(power, laps, fid) if laps else []
        have = {c.target_label for c in cps}
        for c in _find_cp_in_power(power, fid):
            if c.target_label not in have:
                cps.append(c)
        all_cps.extend(cps)

    # Score CP maximality vs athlete best for the same duration.
    for c in all_cps:
        best = athlete_best.get(c.duration_s) or athlete_best.get(
            {"cp3": 180, "cp6": 360, "cp12": 720}[c.target_label], 0.0
        )
        c.maximality = float(np.clip(c.mean_w / best, 0.0, 1.0)) if best > 0 else 0.0

    # Best sprint = highest mean among the genuinely sprint-shaped ones.
    best_sprint = max(all_sprints, key=lambda s: s.mean_w) if all_sprints else None
    proposal.sprint = best_sprint

    # Best CP per target = highest mean, preferring lap-sourced and steady.
    by_target: Dict[str, CPCandidate] = {}
    for c in all_cps:
        key = c.target_label
        if key not in by_target:
            by_target[key] = c
        else:
            cur = by_target[key]
            better = (c.source == "lap" and cur.source != "lap") or (c.mean_w > cur.mean_w)
            if better:
                by_target[key] = c
    proposal.cp_candidates = list(by_target.values())

    # Build the MMP that will feed the metabolic fit (sprint + CP anchors).
    mmp: Dict[int, float] = {}
    if best_sprint is not None:
        mmp[1] = best_sprint.peak_1s_w
        mmp[best_sprint.duration_s] = best_sprint.mean_w
    for c in proposal.cp_candidates:
        mmp[c.duration_s] = c.mean_w
    proposal.mmp_for_fit = dict(sorted(mmp.items()))

    # ---- confidence + status ----
    # Maximality is the key discriminator between a real CP *test* and a
    # merely-steady block inside a ride. A test block sits at ~100% of the
    # athlete's best for that duration; a ride tempo block sits well below.
    # We therefore treat maximality as a gate: blocks far below best are not
    # accepted as test anchors, regardless of how steady they are.
    MAXIMALITY_TEST_THRESHOLD = 0.95   # within 5% of best == plausibly maximal

    maximal_cps = [c for c in proposal.cp_candidates if c.maximality >= MAXIMALITY_TEST_THRESHOLD]
    submaximal_cps = [c for c in proposal.cp_candidates if c.maximality < MAXIMALITY_TEST_THRESHOLD]

    conf = 0.0
    if best_sprint is not None:
        conf += 0.35 * float(np.clip((best_sprint.sustain_ratio - 0.4) / 0.4, 0.0, 1.0))
        if best_sprint.source == "lap":
            conf += 0.05
    else:
        proposal.warnings.append("No valid sprint found - VLamax cannot be anchored.")

    n_max = len(maximal_cps)
    n_cp = len(proposal.cp_candidates)
    conf += 0.45 * (n_max / 3.0)            # only *maximal* CP blocks build confidence
    if n_max < 2:
        proposal.warnings.append(
            f"Only {n_max} maximal CP block(s) found (of {n_cp} steady blocks) - "
            f"aerobic test anchor weak. Sub-maximal blocks look like ride tempo, not test efforts."
        )
    if submaximal_cps:
        avg_sub = float(np.mean([c.maximality for c in submaximal_cps]))
        proposal.warnings.append(
            f"{len(submaximal_cps)} steady block(s) at ~{avg_sub*100:.0f}% of best treated as "
            f"NON-test (likely ride tempo, not maximal trials)."
        )
    if maximal_cps:
        conf += 0.15 * float(np.mean([c.maximality for c in maximal_cps]))

    proposal.confidence = float(np.clip(conf, 0.0, 1.0))

    # Status uses MAXIMAL anchors only. A pile of sub-maximal steady blocks
    # from rides must NOT read as a confirmed test.
    if best_sprint is not None and n_max >= 2:
        proposal.status = "proposed"
        proposal.notes.append("Maximal sprint + CP anchors found; review and confirm to set the profile.")
    elif best_sprint is not None or n_max >= 1:
        proposal.status = "incomplete"
        proposal.notes.append("Partial maximal anchors; a full Flow-style test (sprint + CP3/6/12) is recommended.")
    else:
        proposal.status = "empty"
        proposal.notes.append(
            "No maximal test efforts detected. Steady blocks from rides are not used as test anchors."
        )

    return proposal
