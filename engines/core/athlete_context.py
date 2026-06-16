"""
AthleteContext — shared physiological context model
Version: 1.1.0

Shared module across engines (HRV, Metabolic, etc.) for:
- robust user-input validation
- graceful degradation with neutral physiological defaults
- context-aware physiological getters

CHANGELOG vs 1.0.0
------------------
- Completed the 4 missing getters that MetabolicProfiler already called:
  expected_eta(), vlamax_initial_guess(), tau_base_floor(),
  phenotype_thresholds().
- Fix: cho_oxidation_coefficient() now returns float (1.0) for FEMALE as well —
  previously it returned int (1), violating the signature.
- All new getters are pure functions of (gender, training_years, discipline)
  and never raise exceptions.
"""

from dataclasses import dataclass
from typing import Optional, Tuple, List
import numpy as np


# =============================================================================
# NEUTRAL PHYSIOLOGICAL DEFAULTS (graceful degradation)
# =============================================================================

_DEFAULT_GENDER = "MALE"
_DEFAULT_TRAINING_YEARS = 5.0
_DEFAULT_DISCIPLINE = "MIXED"

_VALID_GENDERS = frozenset({"MALE", "FEMALE"})
_VALID_DISCIPLINES = frozenset({"ENDURANCE", "MIXED", "SPRINT"})

# Mapping from cycling sport names (commonly used by coaches and athletes)
# to the three physiological categories the model actually uses. This is a
# pragmatic mapping based on the dominant energetic demands of each discipline:
#   - ROAD endurance / GRAVEL / MTB-XCM / TRIATHLON: heavy aerobic emphasis
#   - MTB-XCO / CYCLOCROSS / CRITERIUM: mixed aerobic-anaerobic
#   - TRACK sprint / BMX / TT-PURSUIT: glycolytic emphasis
# Used by effective_discipline() to accept either physiological categories
# (ENDURANCE/MIXED/SPRINT) or sport names (ROAD/MTB/TT/TRACK/GRAVEL/...).
_SPORT_TO_DISCIPLINE = {
    # Endurance-leaning
    "ROAD":          "ENDURANCE",
    "GRAVEL":        "ENDURANCE",
    "TRIATHLON":     "ENDURANCE",
    "TT":            "ENDURANCE",         # individual TT — long aerobic
    "TIME_TRIAL":    "ENDURANCE",
    "ULTRA":         "ENDURANCE",
    "MTB_XCM":       "ENDURANCE",         # marathon
    "MARATHON":      "ENDURANCE",
    # Mixed
    "MTB":           "MIXED",             # XCO by default
    "MTB_XCO":       "MIXED",
    "CX":            "MIXED",
    "CYCLOCROSS":    "MIXED",
    "CRITERIUM":     "MIXED",
    "GRAN_FONDO":    "MIXED",
    # Sprint-leaning
    "TRACK":         "SPRINT",
    "TRACK_SPRINT":  "SPRINT",
    "BMX":           "SPRINT",
    "KEIRIN":        "SPRINT",
}


# =============================================================================
# PHYSIOLOGICAL CONSTANTS FOR DERIVED GETTERS
# =============================================================================

# Gross mechanical efficiency in cycling (P_mech / P_metab):
# Coyle 1991: 0.18-0.23 in the general population. Joyner & Coyle 2008: elite ~0.245.
# Linear modulation over training_years [0..10] years.
_ETA_MIN = 0.205   # beginner
_ETA_MAX = 0.245   # elite (>=10 years)
_ETA_SATURATION_YEARS = 10.0

# Floor of the lactate-kinetics time constant (s).
# Beneke 2003 + Mader: lower tau in trained athletes for faster clearance.
# Linear modulation over training_years [0..10] years.
_TAU_FLOOR_MIN = 10.0   # elite, fast clearance
_TAU_FLOOR_MAX = 18.0   # beginner
_TAU_SATURATION_YEARS = 10.0

# vlamax thresholds (mmol/L/s) for metabolic phenotype classification.
# Mader/Heck original: ~0.40 and ~0.60. Modulated by declared discipline so
# athletes who identify as "ENDURANCE" are more easily classified as such, and
# symmetrically for SPRINT (light Bayesian prior).
_PHENO_THRESHOLDS_BY_DISCIPLINE = {
    "ENDURANCE": (0.35, 0.50),
    "MIXED":     (0.40, 0.55),
    "SPRINT":    (0.45, 0.65),
}

# Initial vlamax guess for least_squares optimization.
# Discipline-specific starting values reduce the chance of local minima when
# starting already near the plausible phenotype.
_VLAMAX_INIT_BY_DISCIPLINE = {
    "ENDURANCE": 0.35,
    "MIXED":     0.50,
    "SPRINT":    0.70,
}


# =============================================================================
# MODEL
# =============================================================================

@dataclass(frozen=True)
class AthleteContext:
    """
    Athlete biographical/physiological context.

    All fields are Optional: when absent or invalid, the system applies neutral
    physiological fallbacks and reports via inferred_fields() which values were
    inferred.

    Fields:
      - gender: "MALE" | "FEMALE"
      - training_years: years of structured training
      - discipline: physiological category or cycling sport name. Accepts:
          Physiological: "ENDURANCE" | "MIXED" | "SPRINT"
          Sport names:   "ROAD" | "TT" | "TIME_TRIAL" | "GRAVEL" | "TRIATHLON"
                         | "MTB" | "MTB_XCO" | "MTB_XCM" | "CYCLOCROSS" | "CX"
                         | "CRITERIUM" | "GRAN_FONDO" | "MARATHON" | "ULTRA"
                         | "TRACK" | "TRACK_SPRINT" | "BMX" | "KEIRIN"
        Sport names are mapped internally to one of the three physiological
        categories. See _SPORT_TO_DISCIPLINE for the full mapping.
      - body_fat_pct: body-fat percentage
    """

    gender: Optional[str] = None
    training_years: Optional[float] = None
    discipline: Optional[str] = None
    body_fat_pct: Optional[float] = None

    # -------------------------------------------------------------------------
    # Robust resolution (never raises)
    # -------------------------------------------------------------------------

    def effective_gender(self) -> str:
        if self.gender is None:
            return _DEFAULT_GENDER
        try:
            g = str(self.gender).strip().upper()
            return g if g in _VALID_GENDERS else _DEFAULT_GENDER
        except Exception:
            return _DEFAULT_GENDER

    def effective_training_years(self) -> float:
        if self.training_years is None:
            return _DEFAULT_TRAINING_YEARS
        try:
            v = float(self.training_years)
            if not np.isfinite(v):
                return _DEFAULT_TRAINING_YEARS
            return max(0.0, v)
        except (TypeError, ValueError):
            return _DEFAULT_TRAINING_YEARS

    def effective_discipline(self) -> str:
        """
        Resolve the input discipline to one of {ENDURANCE, MIXED, SPRINT}.
        
        Accepts either:
          - A physiological category directly (ENDURANCE, MIXED, SPRINT)
          - A cycling sport name (ROAD, MTB, TT, TRACK, GRAVEL, CYCLOCROSS,
            BMX, TRIATHLON, ...). See _SPORT_TO_DISCIPLINE for the full list.
        
        Falls back to DEFAULT_DISCIPLINE (MIXED) for unknown values.
        """
        if self.discipline is None:
            return _DEFAULT_DISCIPLINE
        try:
            d = str(self.discipline).strip().upper().replace("-", "_").replace(" ", "_")
            if d in _VALID_DISCIPLINES:
                return d
            # Try sport-name mapping
            mapped = _SPORT_TO_DISCIPLINE.get(d)
            if mapped is not None:
                return mapped
            return _DEFAULT_DISCIPLINE
        except Exception:
            return _DEFAULT_DISCIPLINE

    def effective_body_fat(self) -> float:
        """
        If body_fat_pct is valid -> use the provided value.
        Otherwise apply sex-specific defaults:
          - MALE: 15%
          - FEMALE: 22%
        """
        if self.body_fat_pct is not None:
            try:
                v = float(self.body_fat_pct)
                if np.isfinite(v):
                    return v
            except (TypeError, ValueError):
                pass
        return 15.0 if self.effective_gender() == "MALE" else 22.0

    # -------------------------------------------------------------------------
    # Inference audit
    # -------------------------------------------------------------------------

    def inferred_fields(self) -> List[str]:
        """
        List of fields filled with defaults (missing or invalid).
        Useful for API transparency and debugging.
        """
        out: List[str] = []

        if self.gender is None:
            out.append("gender")
        else:
            try:
                if str(self.gender).strip().upper() not in _VALID_GENDERS:
                    out.append("gender")
            except Exception:
                out.append("gender")

        if self.training_years is None:
            out.append("training_years")
        else:
            try:
                v = float(self.training_years)
                if not np.isfinite(v):
                    out.append("training_years")
            except (TypeError, ValueError):
                out.append("training_years")

        if self.discipline is None:
            out.append("discipline")
        else:
            try:
                d = str(self.discipline).strip().upper().replace("-", "_").replace(" ", "_")
                # A discipline is "inferred" only if neither a direct category
                # nor a sport-name mapping recognized it.
                if d not in _VALID_DISCIPLINES and d not in _SPORT_TO_DISCIPLINE:
                    out.append("discipline")
            except Exception:
                out.append("discipline")

        if self.body_fat_pct is None:
            out.append("body_fat_pct")
        else:
            try:
                v = float(self.body_fat_pct)
                if not np.isfinite(v):
                    out.append("body_fat_pct")
            except (TypeError, ValueError):
                out.append("body_fat_pct")

        return out

    # -------------------------------------------------------------------------
    # Derived physiological getters (gender-aware)
    # -------------------------------------------------------------------------

    def active_muscle_fraction(self) -> float:
        """
        Fraction of FFM actively involved in pedaling.
        Robust heuristic values for the general population.
        """
        return 0.31 if self.effective_gender() == "MALE" else 0.28

    def fat_oxidation_coefficient(self) -> float:
        """
        Relative fat-oxidation coefficient.
        Women are on average more fat-oxidation oriented at matched intensity
        (Tarnopolsky 2008, Venables 2005).
        """
        return 0.526 if self.effective_gender() == "MALE" else 0.580

    def cho_oxidation_coefficient(self) -> float:
        """
        Relative carbohydrate-oxidation coefficient.
        Women are on average less CHO-oriented than men.
        """
        return 1.25 if self.effective_gender() == "MALE" else 1.0

    # -------------------------------------------------------------------------
    # Derived physiological getters (training-aware)
    # -------------------------------------------------------------------------

    def expected_eta(self) -> float:
        """
        Expected gross mechanical efficiency (P_mech / P_metab).
        Modulated by training_years: [0 years \u2192 0.205] ... [\u226510 years \u2192 0.245].

        References: Coyle 1991, Joyner & Coyle 2008. Saturation at 10 years is
        consistent with the documented long-term mitochondrial adaptation time course.
        """
        years = self.effective_training_years()
        blend = float(np.clip(years / _ETA_SATURATION_YEARS, 0.0, 1.0))
        return round(_ETA_MIN + (_ETA_MAX - _ETA_MIN) * blend, 4)

    def tau_base_floor(self) -> float:
        """
        Floor of the lactate-kinetics time constant (s).
        Trained athletes have faster clearance \u2192 lower tau.
        Modulated by training_years: [0 years \u2192 18s] ... [\u226510 years \u2192 10s].

        References: Beneke 2003 (clearance rate vs training status).
        """
        years = self.effective_training_years()
        blend = float(np.clip(years / _TAU_SATURATION_YEARS, 0.0, 1.0))
        return round(_TAU_FLOOR_MAX - (_TAU_FLOOR_MAX - _TAU_FLOOR_MIN) * blend, 2)

    # -------------------------------------------------------------------------
    # Derived physiological getters (discipline-aware)
    # -------------------------------------------------------------------------

    def vlamax_initial_guess(self) -> float:
        """
        Starting point for vlamax optimization (mmol/L/s).
        Discipline-aware to reduce the risk of local minima by starting already
        near the athlete's declared phenotype.
        """
        return _VLAMAX_INIT_BY_DISCIPLINE[self.effective_discipline()]

    def phenotype_thresholds(self) -> Tuple[float, float]:
        """
        vlamax thresholds (mmol/L/s) for metabolic classification:
          - vlamax < endurance_max     \u2192 Endurance
          - vlamax <= allrounder_max   \u2192 All-Rounder
          - vlamax > allrounder_max    \u2192 Sprinter (Explosive)

        Thresholds are modulated by declared discipline: athletes who identify as
        ENDURANCE are classified as Endurance at slightly higher vlamax values
        (and symmetrically for SPRINT). This acts as a light Bayesian prior on
        phenotype without forcing the final classification.

        Neutral default (MIXED): (0.40, 0.55), aligned with Mader/Heck.
        """
        return _PHENO_THRESHOLDS_BY_DISCIPLINE[self.effective_discipline()]
