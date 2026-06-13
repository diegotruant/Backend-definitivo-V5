from __future__ import annotations

from typing import Any, Dict

from api.schemas import ManualLoadRequest
from engines.load.manual_load import calculate_manual_load


class LoadService:
    def calculate_manual(self, req: ManualLoadRequest) -> Dict[str, Any]:
        return calculate_manual_load(
            duration_min=req.duration_min,
            rpe=req.rpe,
            modality=req.modality,
            muscle_damage_factor=req.muscle_damage_factor,
            notes=req.notes,
        )
