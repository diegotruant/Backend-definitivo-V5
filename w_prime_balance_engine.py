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

from typing import List, Dict, Any
import numpy as np


def calculate_w_prime_balance(
    power_stream: List[float],
    cp: float,
    w_prime: float,
    tau: float = 546,
) -> List[float]:
    """
    Real-time W' balance tracking.
    
    Returns: List of W' balance values (same length as power_stream)
    """
    balance = [w_prime]
    
    for p in power_stream[1:]:
        dt = 1  # 1 second
        
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
    }


if __name__ == "__main__":
    # Simulate interval workout
    power = [100]*600 + [400]*300 + [150]*300 + [380]*300 + [100]*600  # Warm-up, 2 intervals, cool
    
    balance = calculate_w_prime_balance(power, cp=275, w_prime=18000, tau=546)
    analysis = analyze_w_prime_usage(power, balance, w_prime=18000)
    
    print("W' Balance Analysis:")
    print(f"Min balance: {analysis['min_balance_j']:.0f}J ({analysis['min_balance_pct']:.1f}%)")
    print(f"Critical depletions: {analysis['critical_depletions_count']}")
    print(f"Fully depleted: {analysis['fully_depleted']}")
