"""
HRV / DFA-α1 Engine — modulato da AthleteContext.
Versione: 4.0.0-Local (per-window quality + unified DFA pipeline)

Modulo backend per l'analisi della variabilità cardiaca via DFA-α1
e la detection delle soglie ventilatorie con robustezza migliorata.

CHANGELOG vs 3.0.0-Local
------------------------
- Quality (artifact_ratio, SQI) calcolata PER-FINESTRA, non più globalmente.
- DFA-α1 e diagnostica regressiva unificate in _dfa_alpha1_full(): singolo
  passaggio, garanzia di coerenza tra α₁ pubblicato e R²/CI riportati.
- Sliding DFA implementata localmente: rimossa dipendenza da
  sliding_dfa_alpha1 (la libreria non esponeva diagnostica per-finestra).
- _normal_z_for_ci ora supporta 90/95/97.5/99% via tabella + interpolazione.
- Isteresi forzata: transizioni AEROBIC\u2194ANAEROBIC passano sempre da MIXED.
- _detect_threshold_crossing: persistenza con semantica esplicita (numero
  totale di finestre consecutive sotto soglia richieste, incluso il crossing).
- _correct_ectopic ora iterativo (max 3 passaggi) con convergenza.
- step_seconds esposto nell'API pubblica (era hardcoded a 10s).
- quality_summary aggregato (mean/min/max), non più solo results[0].
- status_basis aggiunto al metadata per chiarezza (smoothed_with_hysteresis).
- Pesi SQI documentati come euristici non validati.
- Rimosso fallback flatline silenzioso in _correct_ectopic.

BREAKING CHANGES per i test
---------------------------
- detect_thresholds_from_activity ora accetta step_seconds.
- quality_summary cambia struttura (campi *_mean, *_min, *_max).
- metadata include nuovi campi (step_s, n_scales_used, status_basis).
- Filtraggio finestre invalide: le finestre con SQI<min o art_ratio>max
  ora vengono escluse dall'output (prima passavano se la qualità globale
  era OK). Output potrebbe essere più corto o frammentato in dataset rumorosi.
"""

from typing import List, Dict, Optional, Tuple, Any
import warnings
import math

import numpy as np

# Manteniamo solo clean_rr_intervals come utility esterna.
# dfa_alpha1 e sliding_dfa_alpha1 non vengono più usati: tutto il calcolo
# DFA passa per _dfa_alpha1_full() in questo modulo, così l'α₁ pubblicato
# e la diagnostica regressiva (R², stderr, CI) provengono dalla stessa pipeline.
from analysis import clean_rr_intervals
from engines.athlete_context import AthleteContext
from metric_contracts import annotate_payload


# =============================================================================
# SOGLIE CANONICHE (Rogers / Gronwald 2020)
# =============================================================================

_DFA_VT1_CANONICAL = 0.75   # Aerobic threshold (AT1 / HRVT)
_DFA_VT2_CANONICAL = 0.50   # Anaerobic threshold (AT2 / HRVT2)


# =============================================================================
# PARAMETRI DI QUALIT\u00c0 / ROBUSTEZZA
# =============================================================================

_MIN_BEATS_DFA = 64
_MIN_RR_MS = 300.0
_MAX_RR_MS = 2000.0
_MAX_REL_JUMP = 0.20               # >20% battito-battito => possibile artefatto
_MAX_ARTIFACT_RATIO = 0.20         # reject finestra se oltre
_MIN_SQI_FOR_VALID = 0.70          # reject finestra se sotto
_MIN_R2_FOR_HIGH_CONF = 0.85
_MIN_SQI_FOR_HIGH_CONF = 0.80      # sotto questo: confidence MEDIUM

# Smoothing / hysteresis
_EMA_ALPHA = 0.35
_HYSTERESIS_BAND = 0.02
_PERSISTENCE_WINDOWS = 2           # finestre consecutive sotto soglia, INCLUSO il crossing

# Scale DFA short-term (Peng et al., Gronwald et al.)
_DFA_N_MIN = 4
_DFA_N_MAX = 16

# Pesi SQI (NB: euristici non validati su dataset esterno)
# I pesi (0.55, 0.30, 0.15) e i bordi del CV-penalty (0.12, 0.25)
# sono stati scelti per produrre SQI\u22480.80 su tracciate "pulite" cycling
# e SQI<0.70 in presenza di forte burden artefattuale (>15%).
# Sostituire con valori validati appena disponibile un dataset di riferimento.
_SQI_W_ARTIFACT = 0.55
_SQI_W_CORR_IMPACT = 0.30
_SQI_W_CV_PENALTY = 0.15
_SQI_CV_LO = 0.12
_SQI_CV_HI = 0.25


# =============================================================================
# RISOLUZIONE PARAMETRI MODULATI DAL CONTEXT
# =============================================================================

def _resolve_dfa_thresholds(context: Optional[AthleteContext]) -> Tuple[float, float]:
    """Restituisce (vt1_threshold, vt2_threshold) modulati da training_years."""
    if context is None:
        return (_DFA_VT1_CANONICAL, _DFA_VT2_CANONICAL)

    years = context.effective_training_years()
    if years >= 10.0:
        return (_DFA_VT1_CANONICAL, _DFA_VT2_CANONICAL)

    blend = max(0.0, years) / 10.0
    vt1 = _DFA_VT1_CANONICAL + 0.03 * (1.0 - blend)
    vt2 = _DFA_VT2_CANONICAL + 0.02 * (1.0 - blend)
    return (round(vt1, 3), round(vt2, 3))


def _resolve_confidence(context: Optional[AthleteContext]) -> str:
    """HIGH per soggetti allenati (\u22653 anni), MEDIUM per novizi."""
    if context is None:
        return "HIGH"
    if context.effective_training_years() < 3.0:
        return "MEDIUM"
    return "HIGH"


def _classify(alpha1: float, vt1: float, vt2: float) -> str:
    """Classifica lo stato metabolico corrente."""
    if alpha1 > vt1:
        return "AEROBIC"
    if alpha1 > vt2:
        return "MIXED"
    return "ANAEROBIC"


# =============================================================================
# QUALITY / ARTIFACT UTILITIES
# =============================================================================

def _winsorize_rr(rr: np.ndarray) -> np.ndarray:
    rr = rr.copy()
    return np.clip(rr, _MIN_RR_MS, _MAX_RR_MS)


def _artifact_mask(rr: np.ndarray) -> np.ndarray:
    """
    True = campione potenzialmente artefatto.
    Criteri:
    - fuori range fisiologico
    - salto relativo battito-battito eccessivo
    """
    if rr.size == 0:
        return np.array([], dtype=bool)

    out_of_range = (rr < _MIN_RR_MS) | (rr > _MAX_RR_MS)

    rel_jump = np.zeros(rr.shape, dtype=float)
    if rr.size > 1:
        prev = rr[:-1]
        curr = rr[1:]
        denom = np.maximum(prev, 1e-6)
        rel = np.abs(curr - prev) / denom
        rel_jump[1:] = rel

    jump_art = rel_jump > _MAX_REL_JUMP
    return out_of_range | jump_art


def _correct_ectopic(rr: np.ndarray, art_mask: np.ndarray, max_passes: int = 3) -> np.ndarray:
    """
    Correzione ectopici iterativa:
    - sostituisce punti artefatti con interpolazione lineare sui validi
    - rivaluta la maschera dopo ogni passaggio
    - converge quando non rileva più artefatti o quando la maschera è stabile

    Solleva ValueError se ci sono <2 punti validi (caller deve gateare prima).
    """
    if rr.size == 0:
        return rr

    valid_count = int((~art_mask).sum())
    if valid_count < 2:
        raise ValueError(
            f"Insufficient valid RR points for ectopic correction ({valid_count})"
        )

    corrected = rr.copy()
    current_mask = art_mask.copy()

    for _ in range(max_passes):
        valid = ~current_mask
        if valid.sum() < 2:
            break

        idx = np.arange(corrected.size)
        if current_mask.any():
            corrected[current_mask] = np.interp(
                idx[current_mask], idx[valid], corrected[valid]
            )

        new_mask = _artifact_mask(corrected)
        if new_mask.sum() == 0 or np.array_equal(new_mask, current_mask):
            break
        current_mask = new_mask

    return corrected


def _compute_sqi(rr_raw: np.ndarray, rr_corr: np.ndarray, art_ratio: float) -> float:
    """
    SQI 0..1, combinando:
    - artifact burden
    - differenza raw vs corrected (normalizzata)
    - variabilità eccessiva non fisiologica
    """
    if rr_raw.size == 0:
        return 0.0

    diff = np.abs(rr_corr - rr_raw)
    med = float(np.median(rr_corr)) if rr_corr.size else 800.0
    med = max(med, 1e-6)
    corr_impact = float(np.median(diff) / med)

    if rr_corr.size > 1 and float(np.mean(rr_corr)) > 0:
        cv = float(np.std(rr_corr) / np.mean(rr_corr))
    else:
        cv = 0.0
    cv_penalty = min(max((cv - _SQI_CV_LO) / (_SQI_CV_HI - _SQI_CV_LO), 0.0), 1.0)

    score = 1.0 - (
        _SQI_W_ARTIFACT * art_ratio
        + _SQI_W_CORR_IMPACT * corr_impact
        + _SQI_W_CV_PENALTY * cv_penalty
    )
    return float(np.clip(score, 0.0, 1.0))


def _prepare_rr_quality(rr_intervals: List[float]) -> Dict[str, Any]:
    """
    Quality assessment per un singolo segmento RR.
    Usato da calculate_dfa_alpha1 (segmento puntuale) e come pulizia
    iniziale globale prima della sliding window.
    """
    rr_raw = np.array(rr_intervals, dtype=float)
    if rr_raw.size == 0:
        return {
            "rr_corrected": rr_raw,
            "artifact_ratio": 1.0,
            "sqi": 0.0,
            "valid": False,
            "rejected_reason": "EMPTY_RR"
        }

    rr_w = _winsorize_rr(rr_raw)
    art_mask = _artifact_mask(rr_w)
    art_ratio = float(np.mean(art_mask))

    # Gate prima della correzione: serve almeno il minimo per interpolare
    valid_count = int((~art_mask).sum())
    if valid_count < 2 or art_ratio > 0.95:
        return {
            "rr_corrected": rr_w,
            "artifact_ratio": round(art_ratio, 4),
            "sqi": 0.0,
            "valid": False,
            "rejected_reason": "EXCESSIVE_ARTIFACTS"
        }

    rr_corr = _correct_ectopic(rr_w, art_mask)
    sqi = _compute_sqi(rr_w, rr_corr, art_ratio)

    valid = (
        (rr_corr.size >= _MIN_BEATS_DFA)
        and (art_ratio <= _MAX_ARTIFACT_RATIO)
        and (sqi >= _MIN_SQI_FOR_VALID)
    )

    rejected_reason = None
    if rr_corr.size < _MIN_BEATS_DFA:
        rejected_reason = "INSUFFICIENT_BEATS"
    elif art_ratio > _MAX_ARTIFACT_RATIO:
        rejected_reason = "HIGH_ARTIFACT_RATIO"
    elif sqi < _MIN_SQI_FOR_VALID:
        rejected_reason = "LOW_SQI"

    return {
        "rr_corrected": rr_corr,
        "artifact_ratio": round(art_ratio, 4),
        "sqi": round(float(sqi), 4),
        "valid": valid,
        "rejected_reason": rejected_reason
    }


# =============================================================================
# UNIFIED DFA-α1 + DIAGNOSTICS (single-pass)
# =============================================================================

# Z-table per CI normali a una coda (two-sided usa 1-α/2).
# Valori dalla distribuzione N(0,1) standard.
_Z_TABLE = {
    0.90: 1.645,
    0.95: 1.960,
    0.975: 2.241,
    0.99: 2.576,
}


def _normal_z_for_ci(ci_level: float = 0.95) -> float:
    """
    Z-score per CI bilaterale al livello richiesto.
    Tabella per i livelli standard, interpolazione lineare per gli intermedi.
    """
    if ci_level in _Z_TABLE:
        return _Z_TABLE[ci_level]

    keys = sorted(_Z_TABLE.keys())
    if ci_level <= keys[0]:
        return _Z_TABLE[keys[0]]
    if ci_level >= keys[-1]:
        return _Z_TABLE[keys[-1]]

    for i in range(len(keys) - 1):
        lo, hi = keys[i], keys[i + 1]
        if lo <= ci_level <= hi:
            t = (ci_level - lo) / (hi - lo)
            return _Z_TABLE[lo] * (1.0 - t) + _Z_TABLE[hi] * t

    return 1.96


def _dfa_alpha1_full(rr: np.ndarray, ci_level: float = 0.95) -> Dict[str, Any]:
    """
    Calcola α₁ DFA + diagnostica di regressione log-log in un singolo passaggio.

    Pipeline:
    - Profilo integrato: y = cumsum(rr - mean(rr))
    - Scale short-term: N=4..16 (lineari, standard letteratura)
    - Per ogni N: detrending lineare per segmento, RMS dei residui
    - F(N) = sqrt(mean(rms²)) — fluctuation function
    - Regressione log-log: log F(N) = α₁ * log N + intercept

    Garantisce che α₁ pubblicato e diagnostica derivino dalla STESSA fit.
    """
    none_result = {
        "alpha1": None,
        "r_squared": None,
        "residual_std": None,
        "slope_stderr": None,
        "ci_low": None,
        "ci_high": None,
        "n_scales_used": 0,
    }

    if rr.size < _MIN_BEATS_DFA:
        return none_result

    # Profilo integrato
    x = rr - np.mean(rr)
    y = np.cumsum(x)
    n = len(y)

    # Scale short-term lineari, limitate da n//4 (servono almeno 2 segmenti)
    nvals = np.arange(_DFA_N_MIN, min(_DFA_N_MAX, n // 4) + 1)
    if nvals.size < 4:
        return none_result

    F: List[float] = []
    N: List[int] = []
    for win in nvals:
        nseg = n // win
        if nseg < 2:
            continue

        y_cut = y[:nseg * win].reshape(nseg, win)
        t = np.arange(win, dtype=float)

        rms_list: List[float] = []
        for seg in y_cut:
            p = np.polyfit(t, seg, 1)
            fit = p[0] * t + p[1]
            res = seg - fit
            rms_list.append(float(np.sqrt(np.mean(res ** 2))))

        f_n = float(np.sqrt(np.mean(np.array(rms_list) ** 2)))
        if f_n > 0:
            F.append(f_n)
            N.append(int(win))

    if len(F) < 4:
        return none_result

    lx = np.log(np.array(N, dtype=float))
    ly = np.log(np.array(F, dtype=float))

    x_mean = float(np.mean(lx))
    y_mean = float(np.mean(ly))
    sxx = float(np.sum((lx - x_mean) ** 2))
    sxy = float(np.sum((lx - x_mean) * (ly - y_mean)))

    if sxx <= 0:
        return none_result

    slope = sxy / sxx  # questo \u00c8 α₁
    intercept = y_mean - slope * x_mean
    y_hat = slope * lx + intercept
    resid = ly - y_hat

    ss_res = float(np.sum(resid ** 2))
    ss_tot = float(np.sum((ly - y_mean) ** 2))
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 1e-12 else None

    dof = len(lx) - 2
    if dof > 0:
        resid_var = ss_res / dof
        resid_std: Optional[float] = math.sqrt(max(resid_var, 0.0))
        slope_stderr: Optional[float] = math.sqrt(max(resid_var / sxx, 0.0))
        z = _normal_z_for_ci(ci_level)
        ci_low: Optional[float] = slope - z * slope_stderr
        ci_high: Optional[float] = slope + z * slope_stderr
    else:
        resid_std = None
        slope_stderr = None
        ci_low = None
        ci_high = None

    return {
        "alpha1": round(float(slope), 3),
        "r_squared": round(float(r2), 4) if r2 is not None else None,
        "residual_std": round(float(resid_std), 6) if resid_std is not None else None,
        "slope_stderr": round(float(slope_stderr), 6) if slope_stderr is not None else None,
        "ci_low": round(float(ci_low), 4) if ci_low is not None else None,
        "ci_high": round(float(ci_high), 4) if ci_high is not None else None,
        "n_scales_used": len(F),
    }


# =============================================================================
# SLIDING DFA (locale, con quality per-finestra)
# =============================================================================

def _sliding_dfa_local(
    rr_corrected: np.ndarray,
    rr_winsorized_raw: np.ndarray,
    window_s: float,
    step_s: float,
    beat_times_s: Optional[np.ndarray] = None,
) -> List[Dict[str, Any]]:
    """
    Sliding DFA-α₁ con diagnostica E qualità per-finestra.

    rr_corrected: serie post-correzione ectopici (per il calcolo DFA e t-cumul)
    rr_winsorized_raw: serie pre-correzione (per artifact_ratio per-finestra)

    Le due array DEVONO avere la stessa lunghezza e mappare 1:1.
    """
    if rr_corrected.size != rr_winsorized_raw.size:
        raise ValueError("rr_corrected and rr_winsorized_raw must have same length")
    if rr_corrected.size < _MIN_BEATS_DFA:
        return []

    # Beat timestamps in elapsed activity seconds when available; otherwise
    # fall back to cumulative RR time starting at zero.
    if beat_times_s is not None and beat_times_s.size == rr_corrected.size:
        t_beats = np.asarray(beat_times_s, dtype=float)
        if not np.all(np.diff(t_beats) >= -1e-6):
            t_beats = np.cumsum(rr_corrected) / 1000.0
    else:
        t_beats = np.cumsum(rr_corrected) / 1000.0
    total_s = float(t_beats[-1])
    first_s = max(0.0, float(t_beats[0]))

    if total_s < window_s:
        return []

    out: List[Dict[str, Any]] = []
    t_start = first_s
    while t_start + window_s <= total_s + 1e-6:
        t_end = t_start + window_s
        mask = (t_beats >= t_start) & (t_beats < t_end)

        if not mask.any():
            t_start += step_s
            continue

        rr_win_corr = rr_corrected[mask]
        rr_win_raw = rr_winsorized_raw[mask]

        if rr_win_corr.size < _MIN_BEATS_DFA:
            t_start += step_s
            continue

        # Quality PER-FINESTRA (sui RR raw winsorized di quella finestra)
        art_mask_w = _artifact_mask(rr_win_raw)
        art_ratio_w = float(np.mean(art_mask_w))
        sqi_w = _compute_sqi(rr_win_raw, rr_win_corr, art_ratio_w)

        valid_w = (art_ratio_w <= _MAX_ARTIFACT_RATIO) and (sqi_w >= _MIN_SQI_FOR_VALID)
        rejected_w: Optional[str] = None
        if not valid_w:
            if art_ratio_w > _MAX_ARTIFACT_RATIO:
                rejected_w = "HIGH_ARTIFACT_RATIO"
            elif sqi_w < _MIN_SQI_FOR_VALID:
                rejected_w = "LOW_SQI"

        # DFA + diagnostica unificate
        full = _dfa_alpha1_full(rr_win_corr)

        if full["alpha1"] is not None:
            hr_avg = 60000.0 / float(np.mean(rr_win_corr))
            out.append({
                "t_center_s": int(t_start + window_s / 2.0),
                "alpha1": full["alpha1"],
                "r_squared": full["r_squared"],
                "residual_std": full["residual_std"],
                "slope_stderr": full["slope_stderr"],
                "ci_low": full["ci_low"],
                "ci_high": full["ci_high"],
                "n_scales_used": full["n_scales_used"],
                "hr_avg": hr_avg,
                "artifact_ratio": round(art_ratio_w, 4),
                "sqi": round(float(sqi_w), 4),
                "valid": valid_w,
                "rejected_reason": rejected_w,
            })

        t_start += step_s

    return out


# =============================================================================
# SMOOTHING / HYSTERESIS
# =============================================================================

def _ema(values: List[float], alpha: float = _EMA_ALPHA) -> List[float]:
    if not values:
        return []
    out = [float(values[0])]
    for v in values[1:]:
        out.append(alpha * float(v) + (1.0 - alpha) * out[-1])
    return out


def _apply_hysteresis_status(alpha_series: List[float], vt1: float, vt2: float) -> List[str]:
    """
    Classificazione robusta con banda di isteresi.
    Le transizioni AEROBIC\u2194ANAEROBIC passano SEMPRE da MIXED come stato
    intermedio obbligatorio, garantendo applicazione coerente della banda
    su entrambe le soglie.
    """
    if not alpha_series:
        return []

    statuses: List[str] = []
    state = _classify(alpha_series[0], vt1, vt2)
    statuses.append(state)

    for a in alpha_series[1:]:
        if state == "AEROBIC":
            if a <= (vt1 - _HYSTERESIS_BAND):
                state = "MIXED"  # mai salto diretto a ANAEROBIC
        elif state == "MIXED":
            if a >= (vt1 + _HYSTERESIS_BAND):
                state = "AEROBIC"
            elif a <= (vt2 - _HYSTERESIS_BAND):
                state = "ANAEROBIC"
        else:  # ANAEROBIC
            if a >= (vt2 + _HYSTERESIS_BAND):
                state = "MIXED"  # mai salto diretto a AEROBIC

        statuses.append(state)

    return statuses


def _power_at_elapsed(
    power_data: List[float],
    elapsed_s: float,
    power_timestamps: Optional[List[float]] = None,
) -> Optional[float]:
    """Interpolate power on the same elapsed-time axis used by RR windows."""
    if not power_data:
        return None

    power = np.asarray(power_data, dtype=float)
    if power_timestamps is None:
        times = np.arange(power.size, dtype=float)
    else:
        times = np.asarray(power_timestamps, dtype=float)
        if times.size != power.size:
            return None

    valid = np.isfinite(times) & np.isfinite(power)
    if valid.sum() == 0:
        return None

    times = times[valid]
    power = power[valid]
    order = np.argsort(times)
    times = times[order]
    power = power[order]

    if elapsed_s < times[0] or elapsed_s > times[-1]:
        return None

    return float(np.interp(elapsed_s, times, power))


def _detect_threshold_crossing(
    results: List[Dict[str, Any]],
    threshold: float,
    power_data: Optional[List[float]] = None,
    power_timestamps: Optional[List[float]] = None,
    persistence_windows: int = _PERSISTENCE_WINDOWS,
) -> Tuple[Optional[Dict[str, Any]], Optional[int], Optional[float]]:
    """
    Trova crossing robusto della soglia DALL'ALTO con persistenza.

    Semantica di persistence_windows:
    "numero TOTALE di finestre consecutive sotto soglia richieste,
    incluso il crossing stesso".
    Quindi persistence_windows=2 \u2192 crossing + 1 finestra successiva sotto.
    persistence_windows=1 \u2192 solo il crossing (no persistenza).
    """
    if persistence_windows < 1:
        raise ValueError("persistence_windows must be >= 1")

    n = len(results)
    if n < 2:
        return None, None, None

    for i in range(1, n):
        prev = results[i - 1]
        curr = results[i]
        prev_a1 = float(prev["alpha1_smoothed"])
        curr_a1 = float(curr["alpha1_smoothed"])

        if not (prev_a1 > threshold and curr_a1 <= threshold):
            continue

        # Crossing al sample i. Verifica le (persistence_windows - 1)
        # finestre SUCCESSIVE a i. Se non ci sono abbastanza dati, scarta.
        end_idx = i + persistence_windows  # exclusive
        if end_idx > n:
            continue

        ok = all(
            float(results[k]["alpha1_smoothed"]) <= threshold
            for k in range(i + 1, end_idx)
        )
        if not ok:
            continue

        t_curr_float = float(curr["timestamp"])
        t_curr = int(round(t_curr_float))
        power_at_threshold: Optional[float] = None

        if power_data is not None:
            t_prev_float = float(prev["timestamp"])
            p_prev = _power_at_elapsed(power_data, t_prev_float, power_timestamps)
            p_curr = _power_at_elapsed(power_data, t_curr_float, power_timestamps)

            if p_prev is not None and p_curr is not None:
                denom = (curr_a1 - prev_a1)
                if abs(denom) > 1e-9:
                    power_at_threshold = float(
                        p_prev + (threshold - prev_a1) * (p_curr - p_prev) / denom
                    )
                else:
                    power_at_threshold = float(p_prev)
            elif p_curr is not None:
                power_at_threshold = float(p_curr)

        return curr, t_curr, power_at_threshold

    return None, None, None


# =============================================================================
# API PUBBLICA
# =============================================================================

def analyze_rr_stream(
    rr_samples: List[Dict[str, Any]],
    window_seconds: int = 120,
    step_seconds: float = 10.0,
    context: Optional[AthleteContext] = None,
) -> List[Dict[str, Any]]:
    """
    Main entry point per processing di un'attività completa.

    Pipeline:
    1) Concatenazione RR + winsorize + correzione ectopici GLOBALE (pulizia)
    2) Sliding DFA con qualità+diagnostica PER-FINESTRA
    3) Filtro finestre invalide (sotto soglie SQI/artifact)
    4) Smoothing α₁ (EMA) + classificazione status con isteresi
    5) Output strutturato con confidence per-finestra
    """
    if not rr_samples:
        return []

    all_rr: List[float] = []
    beat_times: List[float] = []
    all_samples_have_elapsed = True
    for sample in rr_samples:
        rr_values = [float(rr) for rr in (sample.get("rr") or [])]
        all_rr.extend(rr_values)

        elapsed_raw = sample.get("elapsed", sample.get("elapsed_s"))
        try:
            elapsed_s = float(elapsed_raw)
        except (TypeError, ValueError):
            all_samples_have_elapsed = False
            continue

        # FIT RR intervals are associated with a sample timestamp. Place each
        # beat on elapsed activity time so downstream power interpolation uses
        # the same clock as the power stream.
        start_s = elapsed_s - sum(rr_values) / 1000.0
        cursor_s = start_s
        for rr in rr_values:
            cursor_s += rr / 1000.0
            beat_times.append(cursor_s)

    if len(all_rr) < _MIN_BEATS_DFA:
        return []

    vt1, vt2 = _resolve_dfa_thresholds(context)
    base_confidence = _resolve_confidence(context)

    # 1) Pulizia globale (winsorize + correzione)
    rr_arr = np.array(all_rr, dtype=float)
    rr_w = _winsorize_rr(rr_arr)
    art_mask_global = _artifact_mask(rr_w)

    if int((~art_mask_global).sum()) < _MIN_BEATS_DFA:
        warnings.warn("RR stream rejected: insufficient valid beats globally")
        return []

    try:
        rr_corr_global = _correct_ectopic(rr_w, art_mask_global)
    except ValueError as exc:
        warnings.warn(f"Global ectopic correction failed: {exc}")
        return []

    # 2) Sliding DFA con qualità per-finestra
    try:
        windows = _sliding_dfa_local(
            rr_corrected=rr_corr_global,
            rr_winsorized_raw=rr_w,
            window_s=float(window_seconds),
            step_s=float(step_seconds),
            beat_times_s=np.array(beat_times, dtype=float)
            if all_samples_have_elapsed and len(beat_times) == len(all_rr)
            else None,
        )
    except Exception as exc:
        warnings.warn(f"Sliding DFA failed: {exc}")
        return []

    if not windows:
        return []

    # 3) Filtro finestre invalide
    total = len(windows)
    valid_windows = [w for w in windows if w["valid"]]
    rejected_count = total - len(valid_windows)

    if rejected_count > 0:
        ratio = rejected_count / total
        if ratio > 0.30:
            warnings.warn(
                f"DFA: {rejected_count}/{total} ({ratio:.0%}) windows rejected "
                f"by per-window quality gate"
            )

    if not valid_windows:
        return []

    # 4) Smoothing + isteresi
    alpha_series = [w["alpha1"] for w in valid_windows]
    smoothed = _ema(alpha_series, alpha=_EMA_ALPHA)
    statuses = _apply_hysteresis_status(smoothed, vt1, vt2)

    # 5) Output
    output: List[Dict[str, Any]] = []
    for i, w in enumerate(valid_windows):
        a1_s = float(smoothed[i])
        status = statuses[i]

        # Confidence per-finestra
        conf = base_confidence
        if w["r_squared"] is not None and w["r_squared"] < _MIN_R2_FOR_HIGH_CONF:
            conf = "MEDIUM" if conf == "HIGH" else conf
        if w["sqi"] < _MIN_SQI_FOR_HIGH_CONF:
            conf = "MEDIUM" if conf == "HIGH" else conf

        hr = w["hr_avg"]
        output.append({
            "timestamp": w["t_center_s"],
            "alpha1": w["alpha1"],
            "alpha1_smoothed": round(a1_s, 3),
            "heart_rate": round(float(hr), 1) if not np.isnan(hr) else None,
            "status": status,
            "status_basis": "smoothed_with_hysteresis",
            "confidence": conf,
            "interpretation": (
                f"Alpha-1 raw={w['alpha1']:.3f}, smooth={a1_s:.3f}, "
                f"state={status.lower()}"
            ),
            "metadata": {
                "window_s": window_seconds,
                "step_s": step_seconds,
                "vt1_threshold": vt1,
                "vt2_threshold": vt2,
                "artifact_ratio": w["artifact_ratio"],
                "sqi": w["sqi"],
                "rejected_reason": w["rejected_reason"],  # None se valid
                "r_squared": w["r_squared"],
                "residual_std": w["residual_std"],
                "slope_stderr": w["slope_stderr"],
                "ci_low": w["ci_low"],
                "ci_high": w["ci_high"],
                "n_scales_used": w["n_scales_used"],
            }
        })

    return output


def calculate_dfa_alpha1(
    rr_intervals: List[float],
    context: Optional[AthleteContext] = None,
) -> Dict[str, Any]:
    """Calcolo puntuale per segmenti RR brevi con quality gating + diagnostics."""
    if len(rr_intervals) < _MIN_BEATS_DFA:
        return {
            "alpha1": None,
            "status": "INSUFFICIENT_DATA",
            "confidence": "NONE",
            "interpretation": f"Minimum {_MIN_BEATS_DFA} beats required.",
            "metadata": {"r_squared": None}
        }

    vt1, vt2 = _resolve_dfa_thresholds(context)
    confidence = _resolve_confidence(context)

    quality = _prepare_rr_quality(rr_intervals)
    if not quality["valid"]:
        return {
            "alpha1": None,
            "status": "INVALID_WINDOW",
            "confidence": "NONE",
            "interpretation": f"Window rejected: {quality['rejected_reason']}",
            "metadata": {
                "vt1_threshold": vt1,
                "vt2_threshold": vt2,
                "artifact_ratio": quality["artifact_ratio"],
                "sqi": quality["sqi"],
                "rejected_reason": quality["rejected_reason"]
            }
        }

    try:
        # clean_rr_intervals come ulteriore filtro (rimosso outlier residui)
        rr = clean_rr_intervals(np.array(quality["rr_corrected"], dtype=float))
        full = _dfa_alpha1_full(rr)

        if full["alpha1"] is None:
            return {
                "alpha1": None,
                "status": "ERROR",
                "confidence": "NONE",
                "interpretation": "DFA alpha-1 computation returned None.",
                "metadata": {
                    "vt1_threshold": vt1,
                    "vt2_threshold": vt2,
                    "artifact_ratio": quality["artifact_ratio"],
                    "sqi": quality["sqi"],
                    "r_squared": full["r_squared"],
                    "residual_std": full["residual_std"],
                    "slope_stderr": full["slope_stderr"],
                    "ci_low": full["ci_low"],
                    "ci_high": full["ci_high"],
                    "n_scales_used": full["n_scales_used"],
                }
            }

        a1 = full["alpha1"]
        status = _classify(a1, vt1, vt2)

        if full["r_squared"] is not None and full["r_squared"] < _MIN_R2_FOR_HIGH_CONF:
            confidence = "MEDIUM" if confidence == "HIGH" else confidence
        if quality["sqi"] < _MIN_SQI_FOR_HIGH_CONF:
            confidence = "MEDIUM" if confidence == "HIGH" else confidence

        return {
            "alpha1": a1,
            "status": status,
            "confidence": confidence,
            "interpretation": f"Alpha-1: {a1:.3f} ({status})",
            "metadata": {
                "vt1_threshold": vt1,
                "vt2_threshold": vt2,
                "artifact_ratio": quality["artifact_ratio"],
                "sqi": quality["sqi"],
                "rejected_reason": None,
                "r_squared": full["r_squared"],
                "residual_std": full["residual_std"],
                "slope_stderr": full["slope_stderr"],
                "ci_low": full["ci_low"],
                "ci_high": full["ci_high"],
                "n_scales_used": full["n_scales_used"],
            }
        }

    except Exception as exc:
        warnings.warn(f"Point DFA alpha-1 calculation failed: {exc}")
        return {
            "alpha1": None,
            "status": "ERROR",
            "confidence": "NONE",
            "interpretation": "Exception during DFA alpha-1 calculation.",
            "metadata": {
                "vt1_threshold": vt1,
                "vt2_threshold": vt2,
                "artifact_ratio": quality["artifact_ratio"],
                "sqi": quality["sqi"]
            }
        }


def detect_thresholds_from_activity(
    rr_data: List[Dict[str, Any]],
    power_data: Optional[List[float]] = None,
    power_timestamps: Optional[List[float]] = None,
    context: Optional[AthleteContext] = None,
    window_seconds: int = 120,
    step_seconds: float = 10.0,
) -> Dict[str, Any]:
    """
    Rilevamento combinato VT1 + VT2 con:
    - smoothing alpha1 (EMA)
    - crossing robusto con persistenza
    - interpolazione lineare della potenza al crossing
    - quality summary aggregato (mean/min/max) su tutte le finestre valide
    """
    results = analyze_rr_stream(
        rr_data,
        window_seconds=window_seconds,
        step_seconds=step_seconds,
        context=context,
    )
    if not results:
        return annotate_payload({
            "vt1": {"detected": False},
            "vt2": {"detected": False},
            "message": "No valid DFA data."
        }, module_name="hrv_engine", method="dfa_alpha1_threshold_detection", confidence=0.0)

    vt1_th, vt2_th = _resolve_dfa_thresholds(context)
    confidence = _resolve_confidence(context)

    vt1_point, vt1_t, vt1_p = _detect_threshold_crossing(
        results, vt1_th, power_data, power_timestamps
    )
    vt2_point, vt2_t, vt2_p = _detect_threshold_crossing(
        results, vt2_th, power_data, power_timestamps
    )

    # Quality aggregato su TUTTE le finestre valide
    art_ratios = [
        r["metadata"]["artifact_ratio"]
        for r in results
        if r["metadata"].get("artifact_ratio") is not None
    ]
    sqis = [
        r["metadata"]["sqi"]
        for r in results
        if r["metadata"].get("sqi") is not None
    ]
    r2s = [
        r["metadata"]["r_squared"]
        for r in results
        if r["metadata"].get("r_squared") is not None
    ]

    result = {
        "vt1": {
            "detected": vt1_point is not None,
            "time_seconds": vt1_t,
            "power": round(vt1_p, 1) if vt1_p is not None else None,
            "alpha1": vt1_point["alpha1_smoothed"] if vt1_point else None,
            "threshold_used": vt1_th,
            "validation_strength": "STRONG"
        },
        "vt2": {
            "detected": vt2_point is not None,
            "time_seconds": vt2_t,
            "power": round(vt2_p, 1) if vt2_p is not None else None,
            "alpha1": vt2_point["alpha1_smoothed"] if vt2_point else None,
            "threshold_used": vt2_th,
            "validation_strength": "MODERATE"
        },
        "confidence": confidence,
        "context_used": {
            "training_years": context.effective_training_years() if context else None,
            "thresholds_modulated": (
                vt1_th != _DFA_VT1_CANONICAL or vt2_th != _DFA_VT2_CANONICAL
            )
        },
        "quality_summary": {
            "windows_analyzed": len(results),
            "artifact_ratio_mean": round(float(np.mean(art_ratios)), 4) if art_ratios else None,
            "artifact_ratio_max": round(float(np.max(art_ratios)), 4) if art_ratios else None,
            "sqi_mean": round(float(np.mean(sqis)), 4) if sqis else None,
            "sqi_min": round(float(np.min(sqis)), 4) if sqis else None,
            "r_squared_mean": round(float(np.mean(r2s)), 4) if r2s else None,
            "r_squared_min": round(float(np.min(r2s)), 4) if r2s else None,
        },
        "metadata": {
            "window_s": window_seconds,
            "step_s": step_seconds,
            "ema_alpha": _EMA_ALPHA,
            "hysteresis_band": _HYSTERESIS_BAND,
            "persistence_windows": _PERSISTENCE_WINDOWS,
            "dfa_n_min": _DFA_N_MIN,
            "dfa_n_max": _DFA_N_MAX,
            "power_timestamps_provided": power_timestamps is not None,
        }
    }
    confidence_score = {
        "HIGH": 0.9,
        "MEDIUM": 0.7,
        "LOW": 0.45,
        "NONE": 0.0,
    }.get(str(confidence).upper(), 0.7)
    return annotate_payload(
        result,
        module_name="hrv_engine",
        method="dfa_alpha1_threshold_detection",
        confidence=confidence_score,
    )
