"""
W' Balance Real-Time Tracker
Version: 1.0.0

RESEARCH: Skiba 2012, Bartram 2017

Tracks W' (anaerobic work capacity) depletion and reconstitution during intervals.

MODEL:
- Depletion: W'_bal -= (Power - CP) × dt
- Reconstitution: W'_bal += (W' - W'_bal) × (1 - exp(-dt/τ))
- Tau (τ) = 546s (Skiba default) or athlete-specific
"""

import warnings
from typing import Any, Dict, List, Literal, Optional

import numpy as np

from engines.core.metric_contracts import metric_envelope
from engines.core.science_contracts import TauModel, resolve_w_prime_tau


def calculate_w_prime_balance(
    power_stream: List[float],
    cp: float,
    w_prime: float,
    tau: Optional[float] = None,
    dt_s: float = 1.0,
    duration_s: Optional[float] = None,
    *,
    tau_model: TauModel = "skiba_default",
    athlete_profile: Optional[Dict[str, Any]] = None,
    athlete_level: Optional[str] = None,
) -> List[float]:
    """
    Real-time W' balance tracking.

    Args:
        tau: Explicit τ override in seconds. When omitted, resolved from ``tau_model``.
        dt_s: Seconds represented by each power sample (default 1 Hz streams).
        duration_s: Optional ride duration; when set, warns if sample rate
            disagrees with ``dt_s`` by more than 15%.
        tau_model: W′ reconstitution model selector (see resolve_w_prime_tau).
        athlete_profile: Optional dict with ``w_prime_tau_s`` for individualized τ.
        athlete_level: Optional level hint (e.g. elite/pro) for model selection.
    
    Returns: List of W' balance values (same length as power_stream)
    """
    if tau is None:
        tau, _ = resolve_w_prime_tau(
            tau_model,
            athlete_profile=athlete_profile,
            athlete_level=athlete_level,
        )
    if dt_s <= 0:
        raise ValueError("dt_s must be positive")
    if duration_s is not None and duration_s > 0 and len(power_stream) > 1:
        implied_hz = (len(power_stream) - 1) / duration_s
        expected_hz = 1.0 / dt_s
        if abs(implied_hz - expected_hz) > 0.15 * expected_hz:
            warnings.warn(
                (
                    f"Power stream sampling rate ({implied_hz:.3f} Hz) "
                    f"does not match dt_s={dt_s} ({expected_hz:.3f} Hz expected)"
                ),
                stacklevel=2,
            )

    balance = [w_prime]
    
    for p in power_stream[1:]:
        dt = dt_s
        
        if p > cp:
            # Depletion
            depletion = (p - cp) * dt
            new_balance = max(0, balance[-1] - depletion)
        else:
            # Reconstitution is proportional to the remaining W' deficit.
            recovery = (w_prime - balance[-1]) * (1 - np.exp(-dt / tau))
            new_balance = min(w_prime, balance[-1] + recovery)
        
        balance.append(new_balance)
    
    return balance


def analyze_w_prime_usage(
    power_stream: List[float],
    w_balance: List[float],
    w_prime: float,
) -> Dict[str, Any]:
    """Analyze W' usage patterns"""
    min_balance = min(w_balance)
    min_pct = (min_balance / w_prime) * 100
    
    # Count depletions below 20%
    critical_depletions = sum(1 for b in w_balance if b < w_prime * 0.2)
    
    return {
        "min_balance_j": round(min_balance, 0),
        "min_balance_pct": round(min_pct, 1),
        "critical_depletions_count": critical_depletions,
        "fully_depleted": min_pct < 5.0,
        "metric": metric_envelope(
            "w_prime_min_balance",
            round(min_balance, 0),
            unit="J",
            module_name="w_prime_balance_engine",
            method="skiba_w_prime_balance",
            confidence=0.75,
            metadata={"w_prime_j": w_prime},
        ),
    }


if __name__ == "__main__":  # pragma: no cover
    # Simulate interval workout
    power = [100]*600 + [400]*300 + [150]*300 + [380]*300 + [100]*600  # Warm-up, 2 intervals, cool
    
    balance = calculate_w_prime_balance(power, cp=275, w_prime=18000)
    analysis = analyze_w_prime_usage(power, balance, w_prime=18000)
    
    print("W' Balance Analysis:")
    print(f"Min balance: {analysis['min_balance_j']:.0f}J ({analysis['min_balance_pct']:.1f}%)")
    print(f"Critical depletions: {analysis['critical_depletions_count']}")
    print(f"Fully depleted: {analysis['fully_depleted']}")
