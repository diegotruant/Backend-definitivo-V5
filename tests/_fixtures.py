"""Shared sample payloads for contract and roundtrip tests."""

from __future__ import annotations

from typing import Any, Dict


def twin_build_payload() -> Dict[str, Any]:
    return {
        "athlete_id": "athlete_1",
        "athlete_profile": {"weight_kg": 72, "cp_w": 260, "w_prime_j": 19000},
        "metabolic_snapshot": {
            "status": "success",
            "confidence_score": 0.62,
            "vo2max": 52,
            "vlamax": 0.48,
            "mlss_watts": 260,
            "w_prime_j": 19000,
        },
        "rolling_power_curve": {"60": 480, "300": 330, "1200": 275},
    }


def workout_pct_cp() -> Dict[str, Any]:
    return {
        "title": "VO2 + sprint",
        "steps": [
            {"id": "warm", "type": "warmup", "duration_s": 600, "target_pct_cp": 65},
            {"id": "vo2", "type": "work", "duration_s": 240, "target_pct_cp": 118, "is_key_step": True},
            {"id": "rec", "type": "recovery", "duration_s": 240, "target_pct_cp": 55},
            {"id": "sprint", "type": "work", "duration_s": 12, "target_pct_cp": 250, "is_key_step": True},
        ],
    }


def mader_in_person_payload() -> Dict[str, Any]:
    return {
        "test_type": "mader",
        "athlete": {"weight_kg": 72, "sex": "M"},
        "test_data": {
            "steps": [
                {"step": 1, "power_w": 150, "lactate_mmol": 1.2},
                {"step": 2, "power_w": 200, "lactate_mmol": 1.8},
                {"step": 3, "power_w": 230, "lactate_mmol": 2.6},
                {"step": 4, "power_w": 260, "lactate_mmol": 4.1},
                {"step": 5, "power_w": 290, "lactate_mmol": 6.8},
                {"step": 6, "power_w": 320, "lactate_mmol": 10.2},
            ],
            "mmp": {"1200": 285, "3600": 255, "300": 340, "720": 300, "60": 540, "15": 980},
        },
    }


def critical_power_in_person_payload() -> Dict[str, Any]:
    return {
        "test_type": "critical_power",
        "athlete": {"weight_kg": 72},
        "test_data": {
            "efforts": [
                {"duration_s": 180, "power_w": 360},
                {"duration_s": 300, "power_w": 330},
                {"duration_s": 720, "power_w": 295},
            ],
        },
    }


def wingate_in_person_payload() -> Dict[str, Any]:
    return {
        "test_type": "wingate",
        "athlete": {"weight_kg": 72},
        "test_data": {
            "duration_s": 10,
            "power_stream": [900, 850, 800, 750, 700, 650, 600, 550, 500, 450],
            "body_weight_kg": 72,
        },
    }
