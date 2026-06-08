"""
AthleteContext — shared physiological context model
Version: 1.1.0

Modulo condiviso tra engine (HRV, Metabolic, ecc.) per:
- validazione robusta input utente
- graceful degradation con default fisiologici neutri
- getter fisiologici context-aware

CHANGELOG vs 1.0.0
------------------
- Completati i 4 getter mancanti che il MetabolicProfiler già chiamava:
  expected_eta(), vlamax_initial_guess(), tau_base_floor(),
  phenotype_thresholds().
- Fix: cho_oxidation_coefficient() ora restituisce float (1.0) anche per
  FEMALE — prima ritornava int (1), violando la signature.
- Tutti i nuovi getter sono pure functions di (gender, training_years,
  discipline) e non sollevano mai eccezioni.
"""

from dataclasses import dataclass
from typing import Optional, Tuple, List
import numpy as np


# =============================================================================
# DEFAULT FISIOLOGICI NEUTRI (graceful degradation)
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
# COSTANTI FISIOLOGICHE PER I GETTER DERIVATI
# =============================================================================

# Gross mechanical efficiency in ciclismo (P_mech / P_metab):
# Coyle 1991: 0.18-0.23 popolazione generica. Joyner & Coyle 2008: elite ~0.245.
# Modulazione lineare su training_years [0..10] anni.
_ETA_MIN = 0.205   # principiante
_ETA_MAX = 0.245   # elite (>=10 anni)
_ETA_SATURATION_YEARS = 10.0

# Floor della costante di tempo della cinetica del lattato (s).
# Beneke 2003 + Mader: tau ridotto in atleti allenati per clearance più rapida.
# Modulazione lineare su training_years [0..10] anni.
_TAU_FLOOR_MIN = 10.0   # elite, clearance rapida
_TAU_FLOOR_MAX = 18.0   # principiante
_TAU_SATURATION_YEARS = 10.0

# Soglie vlamax (mmol/L/s) per classificazione fenotipo metabolico.
# Mader/Heck originale: ~0.40 e ~0.60. Modulate per disciplina dichiarata
# in modo che chi si dichiara "ENDURANCE" sia più facilmente classificato
# tale, e simmetricamente per SPRINT (priore bayesiano leggero).
_PHENO_THRESHOLDS_BY_DISCIPLINE = {
    "ENDURANCE": (0.35, 0.50),
    "MIXED":     (0.40, 0.55),
    "SPRINT":    (0.45, 0.65),
}

# Initial guess vlamax per l'ottimizzazione least_squares.
# Valore di partenza diverso per disciplina riduce probabilità di minimi
# locali quando si parte già "vicini" al fenotipo plausibile.
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
    Contesto biografico/fisiologico dell'atleta.

    Tutti i campi sono Optional: se assenti o invalidi, il sistema applica
    fallback fisiologici neutri e segnala via inferred_fields() quali valori
    sono stati inferiti.

    Campi:
      - gender: "MALE" | "FEMALE"
      - training_years: anni di allenamento strutturato
      - discipline: physiological category or cycling sport name. Accepts:
          Physiological: "ENDURANCE" | "MIXED" | "SPRINT"
          Sport names:   "ROAD" | "TT" | "TIME_TRIAL" | "GRAVEL" | "TRIATHLON"
                         | "MTB" | "MTB_XCO" | "MTB_XCM" | "CYCLOCROSS" | "CX"
                         | "CRITERIUM" | "GRAN_FONDO" | "MARATHON" | "ULTRA"
                         | "TRACK" | "TRACK_SPRINT" | "BMX" | "KEIRIN"
        Sport names are mapped internally to one of the three physiological
        categories. See _SPORT_TO_DISCIPLINE for the full mapping.
      - body_fat_pct: % massa grassa
    """

    gender: Optional[str] = None
    training_years: Optional[float] = None
    discipline: Optional[str] = None
    body_fat_pct: Optional[float] = None

    # -------------------------------------------------------------------------
    # Risoluzione robusta (mai solleva)
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
        Se body_fat_pct è valido -> usa input.
        Altrimenti default sesso-specifico:
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
    # Audit inferenze
    # -------------------------------------------------------------------------

    def inferred_fields(self) -> List[str]:
        """
        Lista dei campi riempiti con default (assenti o invalidi).
        Utile per trasparenza API e debug.
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
    # Getter fisiologici derivati (gender-aware)
    # -------------------------------------------------------------------------

    def active_muscle_fraction(self) -> float:
        """
        Frazione FFM attivamente coinvolta nel pedalare.
        Valori euristici robusti per popolazione generale.
        """
        return 0.31 if self.effective_gender() == "MALE" else 0.28

    def fat_oxidation_coefficient(self) -> float:
        """
        Coefficiente relativo di ossidazione grassi.
        Donne mediamente più orientate alla fat oxidation a parità di intensità
        (Tarnopolsky 2008, Venables 2005).
        """
        return 0.526 if self.effective_gender() == "MALE" else 0.580

    def cho_oxidation_coefficient(self) -> float:
        """
        Coefficiente relativo di ossidazione carboidrati.
        Donne mediamente meno orientate al CHO rispetto agli uomini.
        """
        return 1.25 if self.effective_gender() == "MALE" else 1.0

    # -------------------------------------------------------------------------
    # Getter fisiologici derivati (training-aware)
    # -------------------------------------------------------------------------

    def expected_eta(self) -> float:
        """
        Efficienza meccanica gross attesa (P_mech / P_metab).
        Modulata da training_years: [0 anni \u2192 0.205] ... [\u226510 anni \u2192 0.245].

        Riferimenti: Coyle 1991, Joyner & Coyle 2008. La saturazione a 10 anni
        è coerente con la time-course documentata di adattamenti
        mitocondriali a lungo termine.
        """
        years = self.effective_training_years()
        blend = float(np.clip(years / _ETA_SATURATION_YEARS, 0.0, 1.0))
        return round(_ETA_MIN + (_ETA_MAX - _ETA_MIN) * blend, 4)

    def tau_base_floor(self) -> float:
        """
        Floor della costante di tempo (s) della cinetica del lattato.
        Atleti allenati hanno clearance più rapida \u2192 tau più basso.
        Modulato da training_years: [0 anni \u2192 18s] ... [\u226510 anni \u2192 10s].

        Riferimenti: Beneke 2003 (clearance rate vs training status).
        """
        years = self.effective_training_years()
        blend = float(np.clip(years / _TAU_SATURATION_YEARS, 0.0, 1.0))
        return round(_TAU_FLOOR_MAX - (_TAU_FLOOR_MAX - _TAU_FLOOR_MIN) * blend, 2)

    # -------------------------------------------------------------------------
    # Getter fisiologici derivati (discipline-aware)
    # -------------------------------------------------------------------------

    def vlamax_initial_guess(self) -> float:
        """
        Punto iniziale per ottimizzazione vlamax (mmol/L/s).
        Discipline-aware per ridurre il rischio di minimi locali partendo
        già "vicini" al fenotipo dichiarato dall'atleta.
        """
        return _VLAMAX_INIT_BY_DISCIPLINE[self.effective_discipline()]

    def phenotype_thresholds(self) -> Tuple[float, float]:
        """
        Soglie vlamax (mmol/L/s) per classificazione metabolica:
          - vlamax < endurance_max     \u2192 Endurance (Diesel)
          - vlamax <= allrounder_max   \u2192 All-Rounder (Passista)
          - vlamax > allrounder_max    \u2192 Sprinter (Esplosivo)

        Le soglie sono modulate dalla discipline dichiarata: chi si dichiara
        ENDURANCE viene classificato Endurance con vlamax leggermente più alta
        (e simmetricamente per SPRINT). Funziona come priore bayesiano leggero
        sul fenotipo, senza forzare la classificazione finale.

        Default neutro (MIXED): (0.40, 0.55), aderente a Mader/Heck.
        """
        return _PHENO_THRESHOLDS_BY_DISCIPLINE[self.effective_discipline()]
