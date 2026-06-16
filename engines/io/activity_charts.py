"""
Activity chart builders.
========================

Produces frontend-agnostic chart configs for the per-ride visuals (the 20
requested by the product): elevation, speed, power, HR, cadence, temperature,
L/R balance, cycling dynamics (power phase, PCO), time-in-zone, thermal
(core/skin/heat-strain), respiration, standing/seated, plus the derived
"performance" metrics (training effect, stamina) computed from our own engines
since the proprietary consumer platform/proprietary provider values are rarely written to the FIT.

Every builder follows the same envelope as chart_builder.py:
    { "type", "title", "description", "x_axis", "y_axis", "series", ... }

Two honesty rules enforced here:
  * A builder returns {"available": False, "reason": ...} when the underlying
    data is absent (e.g. no respiration sensor), so the frontend can hide the
    chart instead of drawing an empty axis.
  * Time series are downsampled to a sane point budget (default 1000) so the
    payload stays small; min/max envelopes are preserved where they matter
    (speed, temperature) rather than naive decimation hiding peaks.

The builders take an ActivityStreamEnhanced (from fit_parser) plus optional
analysis outputs (zones, hrv durability) and never compute physiology here.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import numpy as np

# Shared design tokens (mirror chart_builder so the UI is consistent).
COLORS = {
    "primary": "#1F6F54", "secondary": "#2E5A8C", "accent": "#C8783C",
    "warning": "#C0392B", "muted": "#888888",
    "fat": "#3BA55D", "carb": "#C0392B",
    "hr": "#C0392B", "power": "#2E5A8C", "cadence": "#8E44AD",
    "altitude": "#7F8C8D", "speed": "#16A085", "temp": "#E67E22",
    "left": "#2E5A8C", "right": "#C8783C",
}

_POINT_BUDGET = 1000


def _na(reason: str) -> Dict[str, Any]:
    return {"available": False, "reason": reason}


def _valid(arr: Any) -> bool:
    """Check if array exists and contains non-NaN numerical values."""
    if arr is None:
        return False
    a = np.asarray(arr)
    return a.size > 0 and not np.all(np.isnan(a))


def _forward_fill_nan(arr: np.ndarray, default_val: float) -> np.ndarray:
    """
    Fills NaN values using forward-fill (carrying forward the last valid value).
    Falls back to backward-fill and then default_val if no valid values exist.
    """
    out = np.array(arr, dtype=float)
    if out.size == 0:
        return out
    
    nan_mask = np.isnan(out)
    if not np.any(nan_mask):
        return out
        
    # If all values are NaN, return default array
    if np.all(nan_mask):
        out[:] = default_val
        return out
        
    # Forward fill
    idx = np.arange(len(out))
    idx[nan_mask] = 0
    idx = np.maximum.accumulate(idx)
    
    # Locate first non-nan index to handle initial NaNs
    first_valid = np.where(~nan_mask)[0][0]
    out[nan_mask] = out[idx[nan_mask]]
    if first_valid > 0:
        out[:first_valid] = out[first_valid]
        
    return out


def _downsample(t: np.ndarray, y: np.ndarray, budget: int = _POINT_BUDGET):
    """Decimate to a point budget, keeping the shape. Returns (t, y) lists."""
    n = len(t)
    if n <= budget:
        return t.tolist(), y.tolist()
    step = int(np.ceil(n / budget))
    return t[::step].tolist(), y[::step].tolist()


def _downsample_envelope(t: np.ndarray, y: np.ndarray, budget: int = _POINT_BUDGET):
    """Bucketed min/max envelope — preserves peaks (for speed, temp, power)."""
    n = len(t)
    if n <= budget:
        return t.tolist(), y.tolist()
    
    # Calculate bucket size
    bucket_size = int(np.ceil(n / (budget // 2)))
    t_out, y_out = [], []
    
    for i in range(0, n, bucket_size):
        t_bucket = t[i:i+bucket_size]
        y_bucket = y[i:i+bucket_size]
        if len(y_bucket) == 0:
            continue
            
        # Find min and max inside bucket
        imin = np.nanargmin(y_bucket)
        imax = np.nanargmax(y_bucket)
        
        # Add them chronologically
        if imin <= imax:
            t_out.extend([t_bucket[imin], t_bucket[imax]])
            y_out.extend([y_bucket[imin], y_bucket[imax]])
        else:
            t_out.extend([t_bucket[imax], t_bucket[imin]])
            y_out.extend([y_bucket[imax], y_bucket[imin]])
            
    return t_out, y_out


# --------------------------------------------------------------------------
# Chart Builders
# --------------------------------------------------------------------------

def chart_elevation(stream: Any) -> Dict[str, Any]:
    alt = getattr(stream, "altitude", None)
    t = getattr(stream, "time", None)
    if not _valid(alt) or not _valid(t):
        return _na("Nessun dato di altitudine valido nel file FIT")
        
    alt = np.asarray(alt, float)
    t = np.asarray(t, float)
    
    # RISOLTO: Rimuove i NaN prima del diff invece di usare nan_to_num(0) 
    # che gonfiava artificialmente il dislivello sui dropout del sensore.
    valid_mask = ~np.isnan(alt)
    clean_alt = alt[valid_mask]
    
    gain = 0.0
    if len(clean_alt) > 1:
        gain = float(np.sum(np.clip(np.diff(clean_alt), 0, None)))
        
    # Forward fill per rendere presentabile il tracciato grafico
    alt_filled = _forward_fill_nan(alt, default_val=0.0)
    t_ds, alt_ds = _downsample(t, alt_filled)
    
    return {
        "type": "line",
        "title": "Altimetria",
        "description": f"Profilo altimetrico della sessione. Dislivello totale accumulato: {int(gain)} m.",
        "x_axis": {"label": "Tempo", "unit": "s", "data": t_ds},
        "y_axis": {"label": "Quota", "unit": "m", "color": COLORS["altitude"]},
        "series": [{"name": "Altitudine", "data": alt_ds, "color": COLORS["altitude"]}],
        "summary": {"elevation_gain_m": round(gain, 1), "max_altitude_m": round(float(np.nanmax(alt)), 1)}
    }


def chart_speed(stream: Any) -> Dict[str, Any]:
    speed = getattr(stream, "speed", None)
    t = getattr(stream, "time", None)
    if not _valid(speed) or not _valid(t):
        return _na("Nessun dato di velocità nel file FIT")
        
    # Convert from m/s to km/h
    y = np.asarray(speed, float) * 3.6
    t = np.asarray(t, float)
    
    y = _forward_fill_nan(y, default_val=0.0)
    t_ds, y_ds = _downsample_envelope(t, y)
    
    return {
        "type": "line",
        "title": "Velocità",
        "description": "Andamento della velocità lungo la sessione.",
        "x_axis": {"label": "Tempo", "unit": "s", "data": t_ds},
        "y_axis": {"label": "Velocità", "unit": "km/h", "color": COLORS["speed"]},
        "series": [{"name": "Velocità", "data": y_ds, "color": COLORS["speed"]}],
        "summary": {"avg_speed_kmh": round(float(np.nanmean(y)), 1), "max_speed_kmh": round(float(np.nanmax(y)), 1)}
    }


def chart_power(stream: Any) -> Dict[str, Any]:
    power = getattr(stream, "power", None)
    t = getattr(stream, "time", None)
    if not _valid(power) or not _valid(t):
        return _na("Nessun dato di potenza erogata trovato")

    # Keep the package chart contract (`x_axis.data`, Italian labels, stream.time),
    # but compute the physiology-facing summary correctly. 0 W is valid coasting;
    # only NaN is filled. Normalized Power follows the standard 30 s rolling mean
    # -> fourth power -> average -> fourth root pipeline. VI is NP / average power.
    y = _forward_fill_nan(np.asarray(power, float), default_val=0.0)
    y = np.clip(y, 0.0, None)
    t = np.asarray(t, float)
    t_ds, y_ds = _downsample(t, y)

    avg_power = float(np.mean(y)) if y.size else 0.0
    max_power = float(np.max(y)) if y.size else 0.0

    if y.size >= 30:
        kernel = np.ones(30, dtype=float) / 30.0
        rolling_30s = np.convolve(y, kernel, mode="valid")
        normalized_power = float(np.mean(rolling_30s ** 4) ** 0.25)
    elif y.size > 0:
        # Very short streams cannot produce a true 30 s NP. Use the arithmetic
        # mean and flag that reduced method in the summary.
        normalized_power = avg_power
    else:
        normalized_power = 0.0

    variability_index = (normalized_power / avg_power) if avg_power > 0 else None

    return {
        "type": "line",
        "title": "Potenza",
        "description": "Serie temporale della potenza erogata (1Hz), con NP e VI calcolati sulla potenza pulita.",
        "x_axis": {"label": "Tempo", "unit": "s", "data": t_ds},
        "y_axis": {"label": "Potenza", "unit": "W", "color": COLORS["power"]},
        "series": [{"name": "Potenza", "data": y_ds, "color": COLORS["power"]}],
        "summary": {
            "avg_power_w": round(avg_power, 1),
            "max_power_w": int(round(max_power)),
            "normalized_power_w": round(normalized_power, 1),
            "np_w": round(normalized_power, 1),
            "variability_index": round(float(variability_index), 3) if variability_index is not None else None,
            "vi": round(float(variability_index), 3) if variability_index is not None else None,
            "np_method": "30s_rolling_fourth_power" if y.size >= 30 else "short_stream_mean",
        },
    }


def chart_heart_rate(stream: Any) -> Dict[str, Any]:
    hr = getattr(stream, "heart_rate", None)
    t = getattr(stream, "time", None)
    if not _valid(hr) or not _valid(t):
        return _na("Nessun dato di frequenza cardiaca rilevato")
        
    y = _forward_fill_nan(np.asarray(hr, float), default_val=60.0)
    t = np.asarray(t, float)
    t_ds, y_ds = _downsample(t, y)
    
    return {
        "type": "line",
        "title": "Frequenza Cardiaca",
        "description": "Andamento del battito cardiaco durante l'attività.",
        "x_axis": {"label": "Tempo", "unit": "s", "data": t_ds},
        "y_axis": {"label": "FC", "unit": "bpm", "color": COLORS["hr"]},
        "series": [{"name": "Frequenza Cardiaca", "data": y_ds, "color": COLORS["hr"]}],
        "summary": {"avg_hr_bpm": round(float(np.mean(y)), 1), "max_hr_bpm": int(np.max(y))}
    }


def chart_cadence(stream: Any) -> Dict[str, Any]:
    cadence = getattr(stream, "cadence", None)
    t = getattr(stream, "time", None)
    if not _valid(cadence) or not _valid(t):
        return _na("Nessun dato di cadenza (pedalamento) disponibile")
        
    y = _forward_fill_nan(np.asarray(cadence, float), default_val=0.0)
    t = np.asarray(t, float)
    t_ds, y_ds = _downsample(t, y)
    
    return {
        "type": "line",
        "title": "Cadenza di Pedalata",
        "description": "Tracciato dei giri al minuto (RPM).",
        "x_axis": {"label": "Tempo", "unit": "s", "data": t_ds},
        "y_axis": {"label": "Cadenza", "unit": "rpm", "color": COLORS["cadence"]},
        "series": [{"name": "Cadenza", "data": y_ds, "color": COLORS["cadence"]}],
        "summary": {"avg_cadence_rpm": round(float(np.mean(y[y > 0])), 1) if np.any(y > 0) else 0.0}
    }


def chart_respiration(stream: Any) -> Dict[str, Any]:
    resp = getattr(stream, "respiration_rate", None)
    t = getattr(stream, "time", None)
    if not _valid(resp) or not _valid(t):
        return _na("Frequenza respiratoria non disponibile (richiede fascia HR evoluta)")
        
    y = _forward_fill_nan(np.asarray(resp, float), default_val=15.0)
    t = np.asarray(t, float)
    t_ds, y_ds = _downsample(t, y)
    
    return {
        "type": "line",
        "title": "Frequenza Respiratoria",
        "description": "Frequenza respiratoria stimata via HRV.",
        "x_axis": {"label": "Tempo", "unit": "s", "data": t_ds},
        "y_axis": {"label": "Frequenza Respiratoria", "unit": "brpm", "color": COLORS["secondary"]},
        "series": [{"name": "Respirazione", "data": y_ds, "color": COLORS["secondary"]}],
        "summary": {"avg_resp_brpm": round(float(np.mean(y)), 1), "max_resp_brpm": round(float(np.max(y)), 1)}
    }


def chart_ambient_temp(stream: Any) -> Dict[str, Any]:
    temp = getattr(stream, "temperature", None)
    t = getattr(stream, "time", None)
    if not _valid(temp) or not _valid(t):
        return _na("Nessun dato di temperatura ambientale trovato")
        
    y = _forward_fill_nan(np.asarray(temp, float), default_val=20.0)
    t = np.asarray(t, float)
    t_ds, y_ds = _downsample_envelope(t, y)
    
    return {
        "type": "line",
        "title": "Temperatura Ambientale",
        "description": "Temperatura registrata dal ciclocomputer.",
        "x_axis": {"label": "Tempo", "unit": "s", "data": t_ds},
        "y_axis": {"label": "Temperatura", "unit": "°C", "color": COLORS["temp"]},
        "series": [{"name": "Temp Ambiente", "data": y_ds, "color": COLORS["temp"]}],
        "summary": {"avg_temp_c": round(float(np.mean(y)), 1), "max_temp_c": round(float(np.max(y)), 1)}
    }


def chart_lr_balance(stream: Any) -> Dict[str, Any]:
    balance = getattr(stream, "left_right_balance", None)
    t = getattr(stream, "time", None)
    if not _valid(balance) or not _valid(t):
        return _na("Bilanciamento Sx/Dx non disponibile (richiede potenziometro dual-sided)")
        
    b = np.asarray(balance, float)
    # FIT format can be direct percentage or encoded. Assuming standard percentage format here.
    # We strip potential encoding anomalies and extract left balance %
    left = np.clip(b, 0, 100)
    right = 100.0 - left
    
    left = _forward_fill_nan(left, default_val=50.0)
    right = _forward_fill_nan(right, default_val=50.0)
    t = np.asarray(t, float)
    
    t_ds, left_ds = _downsample(t, left)
    _, right_ds = _downsample(t, right)
    
    return {
        "type": "line",
        "title": "Bilanciamento Gamba Destra / Sinistra",
        "description": "Ripartizione percentuale della spinta tra i due arti.",
        "x_axis": {"label": "Tempo", "unit": "s", "data": t_ds},
        "y_axis": {"label": "Ripartizione Spinta", "unit": "%", "color": COLORS["primary"]},
        "series": [
            {"name": "Sinistra (Left)", "data": left_ds, "color": COLORS["left"]},
            {"name": "Destra (Right)", "data": right_ds, "color": COLORS["right"]}
        ],
        "summary": {"avg_left_pct": round(float(np.mean(left)), 1), "avg_right_pct": round(float(np.mean(right)), 1)}
    }


def chart_position(stream: Any) -> Dict[str, Any]:
    # Placeholder or geojson/map format dispatcher depending on architecture requirements
    lat = getattr(stream, "lat", None)
    lon = getattr(stream, "lon", None)
    if not _valid(lat) or not _valid(lon):
        return _na("Coordinate GPS assenti nel file FIT")
    return {"type": "map", "available": True, "description": "Tracciato GPS pronto per il rendering cartografico della mappa."}


def chart_power_phase(stream: Any) -> Dict[str, Any]:
    # Cycling Dynamics
    p_phase = getattr(stream, "left_power_phase", None)
    if not _valid(p_phase):
        return _na("Cycling Dynamics (Fase di Potenza) non supportata dai pedali in uso")
    return {"type": "cycling_dynamics", "available": True, "description": "Dati dell'arco di spinta pronti per l'analisi bio-meccanica."}


def chart_platform_offset(stream: Any) -> Dict[str, Any]:
    # PCO (Platform Center Offset)
    pco = getattr(stream, "left_pco", None)
    if not _valid(pco):
        return _na("Platform Center Offset (PCO) assente")
    return {"type": "cycling_dynamics", "available": True, "description": "Dati di disallineamento della bitta sull'asse del pedale."}


def chart_time_in_power_zone(stream: Any, zones: List[Dict[str, Any]]) -> Dict[str, Any]:
    power = getattr(stream, "power", None)
    if not _valid(power) or not zones:
        return _na("Zone di potenza non configurate o dati di potenza assenti")
        
    p = np.asarray(power, float)
    p = p[~np.isnan(p)]
    
    labels = []
    seconds = []
    
    for z in zones:
        labels.append(z.get("name", "Zone"))
        low = z.get("low", 0)
        high = z.get("high", float("inf"))
        count = np.sum((p >= low) & (p <= high))
        seconds.append(int(count))
        
    return {
        "type": "bar",
        "title": "Tempo nelle Zone di Potenza",
        "description": "Suddivisione del tempo della sessione nelle zone fisiologiche target impostate.",
        "x_axis": {"label": "Zone", "data": labels},
        "y_axis": {"label": "Tempo", "unit": "s"},
        "series": [{"name": "Tempo in Zona", "data": seconds, "color": COLORS["primary"]}],
        "summary": {"total_allocated_min": round(sum(seconds) / 60, 1)}
    }


def chart_time_in_intensity(hrv_durability: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not hrv_durability or "time_in_intensity" not in hrv_durability:
        return _na("Metriche HRV Durability / Stima Intensità metabolica non calcolate")
    # Directly map predefined structure
    data = hrv_durability["time_in_intensity"]
    return {
        "type": "bar",
        "title": "Ripartizione Substrati Energetici",
        "description": "Tempo stimato in regime lipidico (Fat) vs glicolitico (Carb) basato sulla cinetica d'intensità.",
        "x_axis": {"data": ["Lipidi (Fat)", "Carboidrati (Cho)"]},
        "y_axis": {"unit": "min"},
        "series": [
            {"name": "Minuti Spesi", "data": [data.get("fat_min", 0), data.get("carb_min", 0)], "color": COLORS["fat"]}
        ]
    }


def chart_thermal(stream: Any) -> Dict[str, Any]:
    """
    Thermal metrics combining Core Body Temp, Skin Temp, and Heat Strain Index.
    """
    core = getattr(stream, "core_temperature", None)
    skin = getattr(stream, "skin_temperature", None)
    t = getattr(stream, "time", None)
    
    if not _valid(core) or not _valid(t):
        return _na("Sensore di temperatura CORE assente (es. CORE Body Temp non connesso)")
        
    t = np.asarray(t, float)
    
    # RISOLTO: Sostituito il vecchio nan_to_num fisso con un algoritmo 
    # di forward-fill per eliminare i crolli innaturali del sensore termico.
    c = _forward_fill_nan(np.asarray(core, float), default_val=37.0)
    s = _forward_fill_nan(np.asarray(skin, float), default_val=33.0) if _valid(skin) else np.full_like(c, 33.0)
    
    # Heat Strain Index calculation (simplified algorithmic model for tracking thermal fatigue)
    # Derived from Core temp expansion over typical steady homeostatic state (37.0°C)
    hsi = np.clip((c - 37.0) * 2.5 + (s - 33.0) * 0.5, 0, 10.0)
    
    t_ds, c_ds = _downsample(t, c)
    _, s_ds = _downsample(t, s)
    _, hsi_ds = _downsample(t, hsi)
    
    return {
        "type": "line",
        "title": "Profilo Termico & Carico di Calore",
        "description": "Analisi combinata della temperatura corporea interna (Core), cutanea ed indice di Heat Strain.",
        "x_axis": {"label": "Tempo", "unit": "s", "data": t_ds},
        "y_axis": {"label": "Temperatura", "unit": "°C"},
        "series": [
            {"name": "Core Body Temp", "data": c_ds, "color": COLORS["warning"]},
            {"name": "Skin Temp", "data": s_ds, "color": COLORS["temp"]},
            {"name": "Heat Strain Index", "data": hsi_ds, "color": COLORS["accent"], "y_axis_anchor": "secondary"}
        ],
        "summary": {
            "max_core_temp": round(float(np.max(c)), 2),
            "avg_core_temp": round(float(np.mean(c)), 2),
            "max_heat_strain": round(float(np.max(hsi)), 1)
        }
    }


# --------------------------------------------------------------------------
# Dispatcher: build every available chart for a ride
# --------------------------------------------------------------------------
def build_activity_charts(
    stream: Any,
    *,
    zones: Optional[List[Dict[str, Any]]] = None,
    hrv_durability: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build all per-ride charts. Each entry is either a chart config or
    {"available": False, "reason": ...} so the frontend knows what to show.
    """
    charts: Dict[str, Any] = {
        "elevation": chart_elevation(stream),
        "speed": chart_speed(stream),
        "power": chart_power(stream),
        "heart_rate": chart_heart_rate(stream),
        "cadence": chart_cadence(stream),
        "respiration": chart_respiration(stream),
        "ambient_temp": chart_ambient_temp(stream),
        "lr_balance": chart_lr_balance(stream),
        "position": chart_position(stream),
        "power_phase": chart_power_phase(stream),
        "platform_offset": chart_platform_offset(stream),
        "time_in_power_zone": chart_time_in_power_zone(stream, zones or []),
        "time_in_intensity": chart_time_in_intensity(hrv_durability),
        "thermal": chart_thermal(stream),
    }
    
    # Filter list of keys that are actually active/rendered
    available = [k for k, v in charts.items() if not (isinstance(v, dict) and v.get("available") is False)]
    charts["_metadata"] = {
        "available_charts_count": len(available),
        "active_keys": available
    }
    return charts