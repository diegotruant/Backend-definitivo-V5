"""Environment adjustments — heat, humidity and altitude coaching hints."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from engines.core.metric_contracts import annotate_payload

SCHEMA_VERSION = "environment_adjustment.v1"
PRESCRIPTION_MODEL = "PRESCRIPTION_MODEL"


def _num(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _heat_stress(temp_c: Optional[float], humidity_pct: Optional[float]) -> str:
    if temp_c is None:
        return "unknown"
    humid = humidity_pct if humidity_pct is not None else 50.0
    index = temp_c + 0.05 * max(0.0, humid - 40.0)
    if index >= 32:
        return "high"
    if index >= 26:
        return "moderate"
    if index <= 12:
        return "cold"
    return "low"


def _altitude_power_factor(altitude_m: Optional[float]) -> float:
    if altitude_m is None or altitude_m < 500:
        return 1.0
    if altitude_m < 1500:
        return 0.97
    if altitude_m < 2500:
        return 0.93
    if altitude_m < 3500:
        return 0.88
    return 0.82


def build_environment_adjustment(
    *,
    athlete_id: Optional[str] = None,
    environment_context: Optional[Dict[str, Any]] = None,
    metabolic_snapshot: Optional[Dict[str, Any]] = None,
    session_context: Optional[Dict[str, Any]] = None,
    thermal_state: Optional[Dict[str, Any]] = None,
    twin_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return intensity and fueling adjustments for environmental stress."""
    twin = twin_state or {}
    env = dict(environment_context or {})
    snapshot = metabolic_snapshot or twin.get("metabolic_snapshot") or {}
    session = session_context or {}
    thermal = thermal_state or twin.get("thermal_load") or {}

    temp_c = _num(env.get("temperature_c") or env.get("ambient_temp_c") or env.get("temp_c"))
    humidity = _num(env.get("humidity_pct") or env.get("relative_humidity"))
    altitude_m = _num(env.get("altitude_m") or env.get("elevation_m"))
    wind_kmh = _num(env.get("wind_speed_kmh") or env.get("wind_kmh"))

    if temp_c is None and humidity is None and altitude_m is None:
        return annotate_payload(
            {
                "status": "insufficient_data",
                "schema_version": SCHEMA_VERSION,
                "measurement_tier": PRESCRIPTION_MODEL,
                "reason": "missing_environment_context",
                "limitations": ["Provide temperature_c, humidity_pct and/or altitude_m."],
            },
            module_name="environment_adjustment_engine",
            method="coach_environment_adjustment",
            confidence=0.0,
        )

    heat_level = _heat_stress(temp_c, humidity)
    alt_factor = _altitude_power_factor(altitude_m)
    mlss = _num(snapshot.get("mlss_power_watts") or snapshot.get("mlss_power_w"))
    duration_min = _num(session.get("duration_min") or session.get("planned_duration_min"))

    intensity_cap_pct = 100.0
    notes: List[str] = []
    hydration: List[str] = []

    if heat_level == "high":
        intensity_cap_pct -= 12.0
        notes.append("Cap intervals 10–15% below usual — prioritize cooling and cadence.")
        hydration.append("Increase fluid and sodium intake; pre-cool when possible.")
    elif heat_level == "moderate":
        intensity_cap_pct -= 6.0
        notes.append("Expect higher cardiac drift — use RPE alongside power.")
        hydration.append("Start session well hydrated; plan electrolytes for >90 min.")
    elif heat_level == "cold":
        notes.append("Allow longer warm-up; muscle tension may affect early power.")

    if altitude_m and altitude_m >= 1500:
        intensity_cap_pct *= alt_factor
        notes.append(f"Altitude ~{int(altitude_m)} m — expect lower sustainable power.")
        hydration.append("Hydration needs rise at altitude — monitor headache and sleep.")

    if wind_kmh and wind_kmh >= 25:
        notes.append("Strong wind — pace by effort on exposed sections, not average power.")

    thermal_rise = _num(thermal.get("thermal_rise_rate"))
    if thermal_rise is not None and thermal_rise > 0.03:
        intensity_cap_pct -= 4.0
        notes.append("Historical thermal rise is steep — bias conservative on hot days.")

    adjusted_mlss = round(mlss * (intensity_cap_pct / 100.0), 0) if mlss else None
    if duration_min and duration_min >= 120 and heat_level in {"moderate", "high"}:
        hydration.append("Plan 60–90 g CHO/h only if gut training supports it in heat.")

    payload = {
        "status": "success",
        "schema_version": SCHEMA_VERSION,
        "measurement_tier": PRESCRIPTION_MODEL,
        "athlete_id": athlete_id,
        "environment_adjustment": {
            "heat_stress_level": heat_level,
            "intensity_cap_adjustment_pct": round(intensity_cap_pct, 1),
            "altitude_power_factor": round(alt_factor, 3),
            "adjusted_mlss_hint_w": adjusted_mlss,
            "pacing_notes": notes or ["No major environmental cap — train as planned."],
            "hydration_notes": hydration or ["Standard hydration protocol."],
            "environment_reported": {
                "temperature_c": temp_c,
                "humidity_pct": humidity,
                "altitude_m": altitude_m,
                "wind_speed_kmh": wind_kmh,
            },
        },
        "limitations": [
            "Environmental adjustments are heuristic — individual heat acclimation varies widely.",
            "Pair with core-temperature data when available for tighter thermal caps.",
        ],
    }
    conf = 0.55
    if temp_c is not None and altitude_m is not None:
        conf = 0.7
    elif temp_c is not None or altitude_m is not None:
        conf = 0.62
    return annotate_payload(
        payload,
        module_name="environment_adjustment_engine",
        method="coach_environment_adjustment",
        confidence=conf,
    )
