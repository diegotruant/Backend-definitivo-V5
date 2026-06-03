"""
Lactate Validation Engine — invasive ground-truth calibration
==============================================================

SCOPO
-----
Questo modulo fa una cosa sola: prende i dati REALI di un test del lattato
(test di Mader in presenza, con prelievo capillare a fine di ogni step) e li
usa per VALIDARE il modello metabolico non invasivo (`MetabolicProfiler`,
che stima il profilo dalla sola MMP).

È il momento di ONBOARDING di un atleta nuovo. Esempio: arriva Lorenzo.
Il coach gli fa UNA volta il test del lattato. Da quei dati si ricava la MLSS
"vera" (misurata). La si confronta con la MLSS che il Mader Python predice
dalla MMP di Lorenzo. Se i due valori convergono, il modello è validato PER
LORENZO: da quel momento Lorenzo si monitora all'infinito senza più pungerlo.

DIFFERENZA da `cross_validation_engine.py`
------------------------------------------
  - cross_validation_engine  → valida il Mader Python SENZA lattato, usando
                               come riferimento la potenza osservata nella MMP.
                               Serve DOPO, nel monitoraggio continuo.
  - lactate_validation_engine → valida il Mader Python CONTRO il lattato reale.
                               Serve UNA VOLTA, all'onboarding.

Sono due momenti diversi del ciclo di vita dell'atleta. Non si sovrappongono.

PERCHÉ D-MAX E NON SOGLIA FISSA 4 mmol/L
----------------------------------------
La validazione ha senso solo se il riferimento "vero" nasce da una matematica
INDIPENDENTE da quella del modello che stiamo validando. Il Mader Python usa
una cinetica Michaelis-Menten. Se ricavassimo la MLSS "vera" con lo stesso
modello, confronteremmo il modello con se stesso: validazione nulla.

Il D-max ricava la soglia dalla GEOMETRIA della curva lattato/potenza
(il punto più distante dalla retta che unisce primo e ultimo punto),
senza assumere nessuna soglia fissa e senza usare Michaelis-Menten.
È quindi un riferimento metodologicamente indipendente — l'unico onesto.

Calcoliamo comunque anche la soglia fissa 4 mmol/L (OBLA classica di Mader)
perché costa zero e dà confrontabilità con i dati storici.

REQUISITO DI PROTOCOLLO
-----------------------
Il D-max ha bisogno di almeno MIN_LACTATE_STEPS punti per essere affidabile:
con 3 o meno punti la "curva" è troppo povera e il D-max diventa rumore.
Il modulo RIFIUTA input con troppi pochi step e spiega perché. In pratica
questo impone al coach il protocollo corretto (step incrementali fino a
lattato chiaramente sovra-soglia).

Tier: REFERENCE (la misura da lattato è ground truth; il giudizio di
validazione è MODEL).
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

# annotate_payload: stessa funzione usata dagli altri moduli del backend per
# etichettare l'output con modulo/metodo/confidenza/limitazioni. La firma è
# dedotta dalle chiamate in metabolic_profiler.py e metabolic_flexibility_engine.py.
# Se metric_contracts non è importabile (es. in test isolati), usiamo un
# fallback che restituisce il payload invariato, così il modulo resta usabile.
try:
    from metric_contracts import annotate_payload
except Exception:  # pragma: no cover
    def annotate_payload(payload, **kwargs):  # type: ignore
        return payload


# =============================================================================
# Parametri del metodo
# =============================================================================

# Numero minimo di step lattato per un D-max affidabile.
MIN_LACTATE_STEPS = 5

# Soglia fissa OBLA classica (Mader 1976): lattato = 4 mmol/L.
OBLA_THRESHOLD_MMOL = 4.0
# Soglia aerobica classica (LT1 approssimata): lattato = 2 mmol/L.
AEROBIC_THRESHOLD_MMOL = 2.0

# Tolleranza di validazione: di quanto può discostarsi la MLSS predetta dal
# Mader Python dalla MLSS vera (D-max) prima di considerare il modello
# NON validato per quell'atleta. Espressa in percentuale della MLSS vera.
# 8% riflette la variabilità biologica tipica della letteratura MLSS.
VALIDATION_TOLERANCE_PCT = 8.0


# =============================================================================
# Strutture dati
# =============================================================================

@dataclass
class LactateStep:
    """Un singolo step del test del lattato."""
    power_w: float          # potenza media tenuta nello step (W)
    lactate_mmol: float     # lattato a fine step (mmol/L)
    hr_mean: Optional[float] = None      # FC media nello step (bpm)
    cadence_mean: Optional[float] = None # cadenza media (rpm)
    duration_s: Optional[float] = None   # durata step (s)


@dataclass
class LactateThresholds:
    """Soglie ricavate dai dati lattato reali (ground truth)."""
    mlss_dmax_w: Optional[float] = None       # MLSS via D-max (riferimento principale)
    obla_4mmol_w: Optional[float] = None       # soglia 4 mmol/L classica
    aerobic_2mmol_w: Optional[float] = None    # soglia 2 mmol/L (LT1 approssimata)
    dmax_lactate_at_threshold: Optional[float] = None  # lattato al punto D-max

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mlss_dmax_watts": self.mlss_dmax_w,
            "obla_4mmol_watts": self.obla_4mmol_w,
            "aerobic_2mmol_watts": self.aerobic_2mmol_w,
            "lactate_at_dmax_mmol": self.dmax_lactate_at_threshold,
        }


# =============================================================================
# Calcolo soglie dai dati lattato
# =============================================================================

def _sorted_steps(steps: List[LactateStep]) -> Tuple[np.ndarray, np.ndarray]:
    """Ritorna (potenze, lattati) ordinati per potenza crescente."""
    pairs = sorted(
        ((s.power_w, s.lactate_mmol) for s in steps if s.power_w > 0 and s.lactate_mmol > 0),
        key=lambda x: x[0],
    )
    powers = np.array([p for p, _ in pairs], dtype=float)
    lacts = np.array([l for _, l in pairs], dtype=float)
    return powers, lacts


def _interpolate_power_at_lactate(
    powers: np.ndarray, lacts: np.ndarray, target_lactate: float
) -> Optional[float]:
    """
    Trova la potenza a cui il lattato raggiunge `target_lactate`,
    interpolando linearmente tra i due step che lo racchiudono.
    Ritorna None se la soglia non è attraversata dai dati.
    """
    for i in range(len(powers) - 1):
        l0, l1 = lacts[i], lacts[i + 1]
        if (l0 <= target_lactate <= l1) or (l1 <= target_lactate <= l0):
            if abs(l1 - l0) < 1e-9:
                return float(powers[i])
            frac = (target_lactate - l0) / (l1 - l0)
            return float(powers[i] + frac * (powers[i + 1] - powers[i]))
    return None


def _dmax_threshold(
    powers: np.ndarray, lacts: np.ndarray
) -> Tuple[Optional[float], Optional[float]]:
    """
    D-max modificato.

    Costruisce la retta che congiunge il primo e l'ultimo punto della curva
    lattato/potenza, poi trova il punto della curva con la massima distanza
    perpendicolare da quella retta. La potenza di quel punto è la soglia.

    Ritorna (potenza_soglia, lattato_alla_soglia). None se non calcolabile.

    Nota: questo è il D-max "modificato" perché lavora sui punti misurati
    (non su un polinomio fittato). Per curve lattato ben formate con 5+ punti
    è stabile e standard nella letteratura moderna.
    """
    if len(powers) < 3:
        return None, None

    x0, y0 = powers[0], lacts[0]
    x1, y1 = powers[-1], lacts[-1]

    dx, dy = x1 - x0, y1 - y0
    line_len = np.hypot(dx, dy)
    if line_len < 1e-9:
        return None, None

    # Distanza perpendicolare di ogni punto dalla retta (primo→ultimo).
    # Usiamo la formula del prodotto vettoriale 2D / lunghezza segmento.
    best_idx = None
    best_dist = -1.0
    for i in range(1, len(powers) - 1):  # estremi esclusi: distanza nulla
        px, py = powers[i], lacts[i]
        dist = abs(dy * (px - x0) - dx * (py - y0)) / line_len
        if dist > best_dist:
            best_dist = dist
            best_idx = i

    if best_idx is None:
        return None, None
    return float(powers[best_idx]), float(lacts[best_idx])


def compute_lactate_thresholds(steps: List[LactateStep]) -> LactateThresholds:
    """
    Calcola le soglie dai dati lattato reali.

    - MLSS via D-max → riferimento principale (indipendente da Mader)
    - OBLA 4 mmol/L → confrontabilità storica
    - Soglia aerobica 2 mmol/L → LT1 approssimata
    """
    powers, lacts = _sorted_steps(steps)
    thr = LactateThresholds()

    if len(powers) < 3:
        return thr  # non abbastanza punti; il chiamante gestisce l'errore

    dmax_w, dmax_lact = _dmax_threshold(powers, lacts)
    thr.mlss_dmax_w = round(dmax_w, 1) if dmax_w is not None else None
    thr.dmax_lactate_at_threshold = round(dmax_lact, 2) if dmax_lact is not None else None

    obla = _interpolate_power_at_lactate(powers, lacts, OBLA_THRESHOLD_MMOL)
    thr.obla_4mmol_w = round(obla, 1) if obla is not None else None

    aer = _interpolate_power_at_lactate(powers, lacts, AEROBIC_THRESHOLD_MMOL)
    thr.aerobic_2mmol_w = round(aer, 1) if aer is not None else None

    return thr


# =============================================================================
# Validazione del modello non invasivo contro il lattato reale
# =============================================================================

def validate_model_against_lactate(
    steps: List[LactateStep],
    profiler,
    mmp: Dict[Any, float],
    expected_eta: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Valida il Mader Python (MetabolicProfiler) contro il lattato reale.

    Parametri
    ---------
    steps : list[LactateStep]
        Gli step del test del lattato (potenza + lattato a fine step).
    profiler : MetabolicProfiler
        Istanza già costruita col peso e il contesto dell'atleta.
    mmp : dict
        La MMP dell'atleta {durata_s: watt}. È quella su cui il Mader Python
        stima il profilo, da confrontare col lattato.
    expected_eta : float, optional
        Efficienza meccanica da passare al profiler (altrimenti la risolve lui).

    Ritorna
    -------
    dict
        Payload JSON con: soglie da lattato, MLSS predetta dal modello,
        scarto, e verdetto di validazione.
    """
    # --- Guardia di protocollo: D-max richiede abbastanza punti ---------
    valid_steps = [s for s in steps if s.power_w > 0 and s.lactate_mmol > 0]
    if len(valid_steps) < MIN_LACTATE_STEPS:
        return annotate_payload(
            {
                "status": "error",
                "reason": "insufficient_lactate_steps",
                "message": (
                    f"Il D-max richiede almeno {MIN_LACTATE_STEPS} step lattato "
                    f"validi; ne sono stati forniti {len(valid_steps)}. Ripetere "
                    f"il test con più gradini di potenza, fino a lattato "
                    f"chiaramente sovra-soglia (>6-8 mmol/L)."
                ),
                "steps_provided": len(valid_steps),
                "steps_required": MIN_LACTATE_STEPS,
            },
            module_name="lactate_validation_engine",
            method="validate_model_against_lactate",
            confidence=0.0,
        )

    # --- 1. Soglie "vere" dal lattato (ground truth) --------------------
    thresholds = compute_lactate_thresholds(valid_steps)
    mlss_true = thresholds.mlss_dmax_w

    if mlss_true is None:
        return annotate_payload(
            {
                "status": "error",
                "reason": "dmax_not_computable",
                "message": (
                    "Impossibile calcolare il D-max: la curva lattato/potenza "
                    "non ha una forma utilizzabile (controllare che il lattato "
                    "cresca con la potenza)."
                ),
                "lactate_thresholds": thresholds.to_dict(),
            },
            module_name="lactate_validation_engine",
            method="validate_model_against_lactate",
            confidence=0.0,
        )

    # --- 2. MLSS predetta dal Mader Python sulla MMP --------------------
    snapshot = profiler.generate_metabolic_snapshot(mmp, expected_eta=expected_eta)

    if snapshot.get("status") != "success":
        return annotate_payload(
            {
                "status": "error",
                "reason": "model_snapshot_failed",
                "message": (
                    "Il modello non invasivo non ha prodotto uno snapshot valido "
                    "sulla MMP fornita: " + str(snapshot.get("message", "errore sconosciuto"))
                ),
                "lactate_thresholds": thresholds.to_dict(),
                "model_snapshot": snapshot,
            },
            module_name="lactate_validation_engine",
            method="validate_model_against_lactate",
            confidence=0.0,
        )

    mlss_model = snapshot.get("mlss_power_watts")
    if mlss_model is None:
        return annotate_payload(
            {
                "status": "error",
                "reason": "model_mlss_unavailable",
                "message": (
                    "Il modello non ha potuto stimare la MLSS dalla MMP "
                    "(probabilmente manca l'ancora di durata soglia 20-60 min "
                    "nella MMP). Vedi 'expressiveness' nello snapshot."
                ),
                "lactate_thresholds": thresholds.to_dict(),
                "model_snapshot": snapshot,
            },
            module_name="lactate_validation_engine",
            method="validate_model_against_lactate",
            confidence=0.0,
        )

    # --- 3. Confronto e verdetto ----------------------------------------
    error_w = float(mlss_model) - float(mlss_true)
    error_pct = 100.0 * error_w / float(mlss_true)
    abs_error_pct = abs(error_pct)

    if abs_error_pct <= VALIDATION_TOLERANCE_PCT:
        validated = True
        severity = "none"
        verdict = (
            f"Modello VALIDATO per questo atleta. La MLSS predetta dalla MMP "
            f"({mlss_model:.0f}W) coincide con la MLSS misurata da lattato "
            f"({mlss_true:.0f}W) entro il {VALIDATION_TOLERANCE_PCT:.0f}% "
            f"(scarto {error_pct:+.1f}%). Da ora il monitoraggio può proseguire "
            f"in modo non invasivo, senza ripetere il test del lattato."
        )
        recommended_action = (
            "Procedere col monitoraggio non invasivo. Rivalutare con un nuovo "
            "test del lattato solo dopo cambiamenti fisiologici importanti "
            "(blocco di allenamento lungo, lunga interruzione, infortunio)."
        )
    elif abs_error_pct <= 2 * VALIDATION_TOLERANCE_PCT:
        validated = False
        severity = "moderate"
        verdict = (
            f"Modello NON ancora validato. La MLSS predetta ({mlss_model:.0f}W) "
            f"si discosta dalla MLSS misurata ({mlss_true:.0f}W) del "
            f"{error_pct:+.1f}%, oltre la tolleranza del "
            f"{VALIDATION_TOLERANCE_PCT:.0f}%. Lo scarto è moderato."
        )
        recommended_action = (
            "Verificare la qualità della MMP (durate soglia presenti? sforzi "
            "massimali recenti?) e la calibrazione del misuratore di potenza "
            "usato nel test. Eventualmente ripetere il test del lattato."
        )
    else:
        validated = False
        severity = "severe"
        verdict = (
            f"Modello NON validato. La MLSS predetta ({mlss_model:.0f}W) si "
            f"discosta fortemente dalla MLSS misurata ({mlss_true:.0f}W): "
            f"{error_pct:+.1f}%. Non usare il modello non invasivo per questo "
            f"atleta finché lo scarto non è chiarito."
        )
        recommended_action = (
            "Scarto eccessivo. Possibili cause: MMP non rappresentativa "
            "(sforzi sub-massimali), power meter del test scalibrato, o "
            "fenotipo atipico fuori dalla calibrazione di default del Mader. "
            "Rivedere i dati di input prima di affidarsi al modello."
        )

    # Confidenza del verdetto: alta se molti step e convergenza netta,
    # ridotta se siamo al limite della tolleranza.
    margin = 1.0 - min(1.0, abs_error_pct / (2 * VALIDATION_TOLERANCE_PCT))
    step_factor = min(1.0, len(valid_steps) / 7.0)  # 7+ step = pieno
    confidence = round(float(np.clip(0.4 + 0.5 * margin * step_factor, 0.2, 0.95)), 3)

    return annotate_payload(
        {
            "status": "success",
            "validated": validated,
            "severity": severity,
            "verdict": verdict,
            "recommended_action": recommended_action,
            "n_lactate_steps": len(valid_steps),
            # Ground truth dal lattato
            "lactate_thresholds": thresholds.to_dict(),
            "mlss_true_watts": mlss_true,
            # Predizione del modello non invasivo
            "mlss_model_watts": round(float(mlss_model), 1),
            # Confronto
            "error_watts": round(error_w, 1),
            "error_pct": round(error_pct, 1),
            "tolerance_pct": VALIDATION_TOLERANCE_PCT,
            # Snapshot completo del modello, per audit
            "model_snapshot": snapshot,
        },
        module_name="lactate_validation_engine",
        method="validate_model_against_lactate",
        confidence=confidence,
        limitations=[
            "MLSS di riferimento stimata via D-max dai punti lattato misurati.",
            "La validazione è specifica per l'atleta testato, non generalizzabile.",
            f"Richiede almeno {MIN_LACTATE_STEPS} step lattato per il D-max.",
        ],
    )


# =============================================================================
# Helper per costruire gli step dal payload JSON dell'app
# =============================================================================

def steps_from_payload(raw_steps: List[Dict[str, Any]]) -> List[LactateStep]:
    """
    Converte la lista di step JSON che arriva dall'app in oggetti LactateStep.

    Formato atteso per ogni step:
        {"power_w": 250, "lactate_mmol": 3.2, "hr_mean": 165,
         "cadence_mean": 92, "duration_s": 300}
    """
    out: List[LactateStep] = []
    for s in raw_steps:
        try:
            out.append(LactateStep(
                power_w=float(s["power_w"]),
                lactate_mmol=float(s["lactate_mmol"]),
                hr_mean=float(s["hr_mean"]) if s.get("hr_mean") is not None else None,
                cadence_mean=float(s["cadence_mean"]) if s.get("cadence_mean") is not None else None,
                duration_s=float(s["duration_s"]) if s.get("duration_s") is not None else None,
            ))
        except (KeyError, TypeError, ValueError):
            continue
    return out


if __name__ == "__main__":
    # Demo con dati sintetici: un atleta con MLSS reale ~250W da lattato.
    demo_steps = [
        LactateStep(power_w=150, lactate_mmol=1.2),
        LactateStep(power_w=200, lactate_mmol=1.8),
        LactateStep(power_w=230, lactate_mmol=2.6),
        LactateStep(power_w=260, lactate_mmol=4.1),
        LactateStep(power_w=290, lactate_mmol=6.8),
        LactateStep(power_w=320, lactate_mmol=10.2),
    ]
    thr = compute_lactate_thresholds(demo_steps)
    print("Soglie da lattato:")
    print("  MLSS (D-max):    ", thr.mlss_dmax_w, "W")
    print("  OBLA (4 mmol/L): ", thr.obla_4mmol_w, "W")
    print("  Aerobica (2):    ", thr.aerobic_2mmol_w, "W")
