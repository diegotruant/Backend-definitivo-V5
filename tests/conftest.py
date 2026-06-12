from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
def simple_power_workout() -> dict[str, Any]:
    return {
        "workout_id": "hardening_simple",
        "title": "Hardening simple intervals",
        "steps": [
            {"step_id": "warmup", "type": "warmup", "duration_s": 60, "target_w": 150},
            {"step_id": "work_1", "type": "work", "duration_s": 90, "target_w": 320, "is_key_step": True},
            {"step_id": "recovery", "type": "recovery", "duration_s": 60, "target_w": 120},
            {"step_id": "work_2", "type": "work", "duration_s": 90, "target_w": 320, "is_key_step": True},
        ],
    }
