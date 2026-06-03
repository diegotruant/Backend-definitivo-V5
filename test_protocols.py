"""
Test Protocols Engine — calcolo dei test in presenza (it4cycling-style)
=======================================================================

SCOPO
-----
Questo modulo riceve i dati di un test eseguito in presenza dal coach (via
l'app tablet collegata al rullo) e ne calcola i risultati, restituendo JSON
pronto per il frontend / lo storico / l'export PDF.

Un test = una funzione. Le funzioni NON ricalcolano cose che il backend sa
già fare: si agganciano ai moduli esistenti.

  - Mader (lattato)   → delega a lactate_validation_engine (D-max + validazione
                        del modello non invasivo). È il test di onboarding.
  - Critical Power     → delega a power_engine.fit_critical_power (fit Monod).
  - Incrementale       → soglia da risposta FC/potenza + max power.
  - Curva P/C          → cadenza ottimale dai picchi di sprint.
  - Wingate            → picco/media/minimo + indice di affaticamento.

Il contratto JSON di input/output è documentato in CONTRATTO_JSON_test.md.

Tier: REFERENCE per i test che applicano formule dirette (curva P/C, wingate,
incrementale max-power); il test Mader eredita il tier del lattato (REFERENCE
sul dato, MODEL sulla validazione); CP eredita da power_engine (REFERENCE).
"""

from typing import Any, Dict, List, Optional
import numpy as np

from metric_contracts import annotate_payload

# Fit CP/W' già esistente nel backend — NON riscriverlo, si chiama.
from power_engine import fit_critical_power

# Validazione col lattato (modulo dedicato) — usato dal test Mader.
from lactate_validation_engine import (
    validate_model_against_lactate,
    steps_from_payload,
)


# =============================================================================
# Helper comuni
# =============================================================================

def _err(reason: str, message: str, method: str, **extra) -> Dict[str, Any]:
    """Costruisce una risposta di errore uniforme e annotata."""
    payload = {"status": "error", "reason": reason, "message": message}
    payload.update(extra)
    return annotate_payload(
        payload,
        module_name="test_protocols",
        method=method,
        confidence=0.0,
    )


def _athlete_weight(envelope: Dict[str, Any], fallback: float = 70.0) -> float:
    """Estrae il peso dell'atleta dalla busta comune."""
    try:
        w = float(envelope.get("athlete", {}).get("weight_kg"))
        return w if w > 0 else fallback
    except (TypeError, ValueError):
        return fallback


# =============================================================================
# 1. MADER (test del lattato) — onboarding
# =============================================================================

def run_mader_test(
    envelope: Dict[str, Any],
    profiler,
) -> Dict[str, Any]:
    """
    Esegue il test di Mader col lattato.

    Delega interamente a lactate_validation_engine: calcola la MLSS vera col
    D-max dai punti lattato, la confronta con la MLSS che il modello non
    invasivo predice dalla MMP, ed emette il verdetto di validazione.

    Parametri
    ---------
    envelope : dict
        La busta completa (vedi contratto). test_data deve contenere
        'steps' (con lattato) e 'mmp'.
    profiler : MetabolicProfiler
        Istanza già costruita col peso/contesto dell'atleta.
    """
    td = envelope.get("test_data", {})
    raw_steps = td.get("steps")
    mmp = td.get("mmp")

    if not raw_steps:
        return _err("missing_steps", "Mancano gli step del test del lattato.",
                    "run_mader_test")
    if not mmp:
        return _err("missing_mmp",
                    "Manca la MMP dell'atleta: serve per validare il modello "
                    "non invasivo contro il lattato.",
                    "run_mader_test")

    steps = steps_from_payload(raw_steps)
    eta = td.get("expected_eta")  # opzionale

    # Tutta la logica vera è qui dentro (D-max + validazione).
    return validate_model_against_lactate(
        steps=steps,
        profiler=profiler,
        mmp=mmp,
        expected_eta=eta,
    )


# =============================================================================
# 2. INCREMENTALE
# =============================================================================

def run_incremental_test(envelope: Dict[str, Any]) -> Dict[str, Any]:
    """
    Test incrementale a potenza crescente (senza lattato).

    Estrae: massima potenza raggiunta, FC massima osservata, numero di step
    completati. La soglia precisa, se serve, va dal modello sulla MMP
    (non da qui): questo test fornisce i dati grezzi e il max-power.
    """
    td = envelope.get("test_data", {})
    steps = td.get("steps")
    if not steps:
        return _err("missing_steps", "Mancano gli step dell'incrementale.",
                    "run_incremental_test")

    powers = [float(s["power_w"]) for s in steps if s.get("power_w")]
    hrs = [float(s["hr_mean"]) for s in steps if s.get("hr_mean")]

    if not powers:
        return _err("no_power_data", "Nessun dato di potenza valido.",
                    "run_incremental_test")

    max_power = max(powers)
    hr_max_obs = max(hrs) if hrs else None

    payload = {
        "status": "success",
        "max_power_w": round(max_power, 1),
        "hr_max_observed": round(hr_max_obs, 0) if hr_max_obs else None,
        "steps_completed": len(steps),
        "notes": (
            "Max-power e FC max dal test. Per la soglia metabolica usare il "
            "modello sulla MMP costruita da questo test."
        ),
    }
    return annotate_payload(
        payload,
        module_name="test_protocols",
        method="run_incremental_test",
        confidence=0.85,  # dato diretto, alta affidabilità
    )


# =============================================================================
# 3. CURVA POTENZA / CADENZA
# =============================================================================

def run_power_cadence_test(envelope: Dict[str, Any]) -> Dict[str, Any]:
    """
    Curva potenza/cadenza da 4-5 sprint massimali a RPM diverse.

    Trova la cadenza a cui l'atleta esprime la potenza di picco massima,
    interpolando una parabola sui punti (modello classico: la potenza in
    funzione della cadenza ha forma a campana).
    """
    td = envelope.get("test_data", {})
    points = td.get("points")
    if not points or len(points) < 3:
        return _err("insufficient_points",
                    "Servono almeno 3 sprint a cadenze diverse per la curva.",
                    "run_power_cadence_test",
                    points_provided=len(points) if points else 0)

    rpms = np.array([float(p["rpm_peak"]) for p in points if p.get("rpm_peak")], dtype=float)
    watts = np.array([float(p["w_peak"]) for p in points if p.get("w_peak")], dtype=float)

    if len(rpms) < 3 or len(rpms) != len(watts):
        return _err("invalid_points", "Punti cadenza/potenza incompleti.",
                    "run_power_cadence_test")

    # Fit parabolico watts = a*rpm^2 + b*rpm + c; il vertice dà la cadenza ottimale.
    optimal_cadence = None
    peak_power_fit = None
    try:
        coeffs = np.polyfit(rpms, watts, 2)
        a, b, c = coeffs
        if a < 0:  # parabola con massimo (campana), come atteso
            vertex_rpm = -b / (2 * a)
            # accetta il vertice solo se cade dentro/vicino al range testato
            if rpms.min() - 10 <= vertex_rpm <= rpms.max() + 10:
                optimal_cadence = float(vertex_rpm)
                peak_power_fit = float(a * vertex_rpm**2 + b * vertex_rpm + c)
    except Exception:
        pass

    # Fallback: se il fit non dà un massimo valido, usa il punto misurato migliore.
    if optimal_cadence is None:
        idx = int(np.argmax(watts))
        optimal_cadence = float(rpms[idx])
        peak_power_fit = float(watts[idx])

    curve = [{"rpm": round(float(r)), "watts": round(float(w))}
             for r, w in sorted(zip(rpms, watts))]

    payload = {
        "status": "success",
        "optimal_cadence_rpm": round(optimal_cadence),
        "peak_power_w": round(peak_power_fit),
        "curve": curve,
    }
    return annotate_payload(
        payload,
        module_name="test_protocols",
        method="run_power_cadence_test",
        confidence=0.80,
    )


# =============================================================================
# 4. CRITICAL POWER
# =============================================================================

def run_critical_power_test(envelope: Dict[str, Any]) -> Dict[str, Any]:
    """
    Test di Critical Power da più prove massimali (2-15 min).

    Delega al fit già esistente in power_engine.fit_critical_power, che vuole
    una lista [{"duration_s": ..., "power_w": ...}].
    """
    td = envelope.get("test_data", {})
    efforts = td.get("efforts")
    if not efforts:
        return _err("missing_efforts", "Mancano le prove per il fit CP.",
                    "run_critical_power_test")

    # fit_critical_power filtra da sé la finestra 120-900s e vuole min 3 punti.
    result = fit_critical_power(efforts)

    if result is None:
        return _err(
            "cp_fit_failed",
            "Fit CP non riuscito: servono almeno 3 prove massimali nella "
            "finestra 2-15 min (120-900s), e CP/W' devono risultare positivi.",
            "run_critical_power_test",
            efforts_provided=len(efforts),
        )

    result["status"] = "success"
    return annotate_payload(
        result,
        module_name="test_protocols",
        method="run_critical_power_test",
        confidence=result.get("r_squared", 0.8),  # R² come proxy di confidenza
    )


# =============================================================================
# 5. WINGATE
# =============================================================================

def run_wingate_test(envelope: Dict[str, Any]) -> Dict[str, Any]:
    """
    Test di Wingate: sprint massimale cronometrato (classico 30s).

    Calcola picco, media, minimo e indice di affaticamento:
        fatigue_index = (picco - minimo) / picco * 100
    """
    td = envelope.get("test_data", {})
    stream = td.get("power_stream")
    if not stream:
        return _err("missing_power_stream",
                    "Manca lo stream di potenza secondo-per-secondo.",
                    "run_wingate_test")

    p = np.array([float(x) for x in stream if x is not None], dtype=float)
    p = p[p >= 0]
    if p.size < 5:
        return _err("stream_too_short",
                    "Stream di potenza troppo corto per un Wingate.",
                    "run_wingate_test")

    weight = _athlete_weight(envelope)
    # peso esplicito nel test_data ha priorità, se presente
    if td.get("body_weight_kg"):
        try:
            weight = float(td["body_weight_kg"])
        except (TypeError, ValueError):
            pass

    peak = float(np.max(p))
    mean = float(np.mean(p))
    minimum = float(np.min(p))
    fatigue_index = (peak - minimum) / peak * 100.0 if peak > 0 else None

    payload = {
        "status": "success",
        "peak_power_w": round(peak, 1),
        "peak_power_wkg": round(peak / weight, 2) if weight > 0 else None,
        "mean_power_w": round(mean, 1),
        "min_power_w": round(minimum, 1),
        "fatigue_index_pct": round(fatigue_index, 1) if fatigue_index is not None else None,
        "duration_s": int(td.get("duration_s", p.size)),
    }
    return annotate_payload(
        payload,
        module_name="test_protocols",
        method="run_wingate_test",
        confidence=0.90,  # misure dirette
    )


# =============================================================================
# Dispatcher: instrada la busta al test giusto
# =============================================================================

def run_test(envelope: Dict[str, Any], profiler=None) -> Dict[str, Any]:
    """
    Punto d'ingresso unico. Legge envelope['test_type'] e chiama la funzione
    giusta. Il profiler serve solo al test Mader (gli altri lo ignorano).
    """
    test_type = envelope.get("test_type")

    if test_type == "mader":
        if profiler is None:
            return _err("profiler_required",
                        "Il test Mader richiede un'istanza di MetabolicProfiler.",
                        "run_test")
        return run_mader_test(envelope, profiler)
    if test_type == "incrementale":
        return run_incremental_test(envelope)
    if test_type == "curva_pc":
        return run_power_cadence_test(envelope)
    if test_type == "critical_power":
        return run_critical_power_test(envelope)
    if test_type == "wingate":
        return run_wingate_test(envelope)

    return _err("unknown_test_type",
                f"Tipo di test sconosciuto: {test_type!r}.",
                "run_test")
