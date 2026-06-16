"""Longitudinal load trend helpers for adaptive load."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

import numpy as np

from engines.performance.training_variability_engine import calculate_acwr, calculate_monotony_strain


def ewma(values: Iterable[float], span: int) -> Optional[float]:
    vals = [float(v) for v in values if v is not None and np.isfinite(float(v))]
    if not vals:
        return None
    alpha = 2.0 / (span + 1.0)
    out = vals[0]
    for value in vals[1:]:
        out = alpha * value + (1.0 - alpha) * out
    return float(out)


def extract_history_loads(history: Optional[list[Dict[str, Any]]]) -> list[float]:
    """Accept flexible persisted history payloads and return daily/session loads."""
    if not history:
        return []
    loads: list[float] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        value = (
            item.get("session_load_score")
            or item.get("session_load")
            or item.get("adaptive_load")
            or item.get("tss")
            or item.get("load")
        )
        try:
            v = float(value)
        except (TypeError, ValueError):
            continue
        if np.isfinite(v) and v >= 0:
            loads.append(v)
    return loads


def extract_dual_series(
    history: Optional[list[Dict[str, Any]]],
) -> tuple[list[float], list[float]]:
    """Estrae due serie parallele dai record storici.

    Restituisce (external_loads, combined_loads):
      - external_loads : solo carico ESTERNO (TSS) — il "nominale"
      - combined_loads : session_load combinato esterno+interno — il "reale"

    Un record contribuisce a una serie solo se quel valore è presente, così le
    due serie restano allineate per indice quando entrambi i campi esistono.
    Quando manca il session_load combinato, si ripiega sul TSS (degradazione
    con grazia: senza segnali interni le due serie coincidono e la divergenza
    è zero, esattamente come il Banister classico).
    """
    if not history:
        return [], []
    external: list[float] = []
    combined: list[float] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        ext_raw = item.get("tss") or item.get("external_load_score")
        comb_raw = (
            item.get("session_load_score")
            or item.get("session_load")
            or item.get("adaptive_load")
            or item.get("load")
            or ext_raw  # fallback: nessun interno -> usa l'esterno
        )
        try:
            ext_v = float(ext_raw) if ext_raw is not None else None
        except (TypeError, ValueError):
            ext_v = None
        try:
            comb_v = float(comb_raw) if comb_raw is not None else None
        except (TypeError, ValueError):
            comb_v = None
        if ext_v is not None and np.isfinite(ext_v) and ext_v >= 0:
            external.append(ext_v)
        if comb_v is not None and np.isfinite(comb_v) and comb_v >= 0:
            combined.append(comb_v)
    return external, combined


def calculate_load_trend(
    history: Optional[list[Dict[str, Any]]],
    current_session_load: Optional[float],
    current_external_load: Optional[float] = None,
) -> Dict[str, Any]:
    loads = extract_history_loads(history)
    if current_session_load is not None:
        loads.append(float(current_session_load))

    if len(loads) < 7:
        return {
            "status": "insufficient_data",
            "days_available": len(loads),
            "atl_7d": None,
            "ctl_42d": None,
            "tsb": None,
            "load_ratio": None,
            "monotony": None,
            "strain": None,
            "message": "Need at least 7 daily/session load values for trend metrics.",
        }

    atl = ewma(loads[-14:], span=7)
    ctl = ewma(loads[-56:], span=42)
    tsb = None if atl is None or ctl is None else ctl - atl

    last_7 = loads[-7:]
    chronic = loads[-42:] if len(loads) >= 42 else loads
    chronic_mean = float(np.mean(chronic)) if chronic else 0.0
    load_ratio = float(np.mean(last_7) / chronic_mean) if chronic_mean > 0 else None

    acwr = calculate_acwr(atl, ctl) if atl is not None and ctl is not None and ctl > 0 else None
    monotony = calculate_monotony_strain(last_7)

    # ------------------------------------------------------------------
    # Binario ESTERNO parallelo + divergenza esterno/interno
    # ------------------------------------------------------------------
    # 'tsb' qui sopra è calcolato sul session_load COMBINATO (esterno+interno):
    # è la freschezza "reale". Tracciamo in parallelo un CTL/ATL/TSB sul SOLO
    # TSS esterno (la freschezza "nominale", quella che vedrebbe coaching platform).
    # La differenza tra i due TSB è il segnale: quando l'esterno dice "fresco"
    # ma l'interno dice "affaticato", è il pre-allarme di overreaching che il
    # carico esterno da solo non vede.
    external_series, _combined = extract_dual_series(history)
    if current_external_load is not None:
        try:
            ext_v = float(current_external_load)
            if np.isfinite(ext_v) and ext_v >= 0:
                external_series.append(ext_v)
        except (TypeError, ValueError):
            pass

    divergence_block: Dict[str, Any] = {"available": False}
    if len(external_series) >= 7:
        atl_ext = ewma(external_series[-14:], span=7)
        ctl_ext = ewma(external_series[-56:], span=42)
        tsb_ext = None if atl_ext is None or ctl_ext is None else ctl_ext - atl_ext
        # divergence = TSB esterno - TSB interno(combinato).
        # > 0  -> l'esterno sopravvaluta la freschezza (fatica interna nascosta)
        # < 0  -> il corpo ha assorbito meglio del nominale
        divergence = None if (tsb_ext is None or tsb is None) else tsb_ext - tsb
        divergence_status = None
        # Soglie calibrate sulla scala 0-100 del session_load di questo backend
        # (non sulla scala TSS pura). Una divergenza realistica su un blocco di
        # carico va da ~3 (lieve) a ~7+ (severo).
        if divergence is not None:
            if divergence >= 6.0:
                divergence_status = "hidden_fatigue"
            elif divergence >= 3.0:
                divergence_status = "watch"
            elif divergence <= -6.0:
                divergence_status = "good_adaptation"
            else:
                divergence_status = "aligned"
        divergence_block = {
            "available": tsb_ext is not None and tsb is not None,
            "atl_7d_external": round(atl_ext, 1) if atl_ext is not None else None,
            "ctl_42d_external": round(ctl_ext, 1) if ctl_ext is not None else None,
            "tsb_external": round(tsb_ext, 1) if tsb_ext is not None else None,
            "tsb_internal": round(tsb, 1) if tsb is not None else None,
            "divergence": round(divergence, 1) if divergence is not None else None,
            "divergence_status": divergence_status,
        }

    return {
        "status": "success",
        "days_available": len(loads),
        "atl_7d": round(atl, 1) if atl is not None else None,
        "ctl_42d": round(ctl, 1) if ctl is not None else None,
        "tsb": round(tsb, 1) if tsb is not None else None,
        "load_ratio": round(load_ratio, 2) if load_ratio is not None else None,
        "acwr": acwr,
        "monotony": monotony.get("monotony") if isinstance(monotony, dict) else None,
        "strain": monotony.get("strain") if isinstance(monotony, dict) else None,
        "monotony_status": monotony.get("monotony_status") if isinstance(monotony, dict) else None,
        "external_internal_divergence": divergence_block,
    }
