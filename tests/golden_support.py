"""Shared helpers for versioned golden scientific regression tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
DEFAULT_TOLERANCE_PCT = 0.5
GOLDEN_VERSION = "golden_scientific.v1"


def load_golden_cases(filename: str) -> list[dict[str, Any]]:
    path = GOLDEN_DIR / filename
    return json.loads(path.read_text(encoding="utf-8"))


def within_pct(actual: float, expected: float, tolerance_pct: float = DEFAULT_TOLERANCE_PCT) -> bool:
    if expected == 0:
        return abs(actual) <= tolerance_pct / 100.0
    return abs(actual - expected) / abs(expected) * 100.0 <= tolerance_pct


def assert_within_pct(
    actual: float,
    expected: float,
    *,
    tolerance_pct: float = DEFAULT_TOLERANCE_PCT,
    label: str = "value",
) -> None:
    assert within_pct(actual, expected, tolerance_pct), (
        f"{label}: actual={actual} expected={expected} tol={tolerance_pct}%"
    )


def assert_in_range(value: float, lo: float, hi: float, *, label: str = "value") -> None:
    assert lo <= value <= hi, f"{label}: {value} not in [{lo}, {hi}]"


def build_power_from_pattern(pattern: dict[str, Any]) -> list[float]:
    if not pattern:
        return []
    if "constant_segments" in pattern:
        power: list[float] = []
        for segment in pattern["constant_segments"]:
            watts, seconds = segment
            power.extend([float(watts)] * int(seconds))
        return power
    if pattern.get("type") == "constant":
        return [float(pattern["power_w"])] * int(pattern["power_len"])
    if pattern.get("type") == "two_segment":
        seg = int(pattern["segment_s"])
        return [float(pattern["first_w"])] * seg + [float(pattern["second_w"])] * seg
    raise ValueError(f"unsupported power pattern: {pattern}")


class MatrixActivityStream:
    """Minimal ActivityStream stand-in for compliance golden cases."""

    def __init__(self, power: Iterable[float] | None = None, heart_rate: Iterable[float] | None = None) -> None:
        power_list = list(power or [])
        hr_list = list(heart_rate or [])
        n = max(len(power_list), len(hr_list))
        self.power = np.array(power_list or [0.0] * n, dtype=float)
        self.heart_rate = np.array(hr_list or [145.0] * n, dtype=float)
        self.cadence = np.zeros(n, dtype=float)
        self.elapsed_s = np.arange(n, dtype=float)
        self.n_samples = n
        self.has_power = bool(power_list)
        self.has_heart_rate = bool(hr_list)
