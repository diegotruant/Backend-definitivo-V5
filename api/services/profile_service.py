from __future__ import annotations

from typing import Any, Dict

from api.schemas import AthleteParams, SnapshotRequest
from engines.core.athlete_context import AthleteContext
from engines.metabolic.metabolic_profiler import MetabolicProfiler


class ProfileService:
    def build_snapshot(self, req: SnapshotRequest) -> Dict[str, Any]:
        ctx = AthleteContext(
            gender=req.athlete.gender or "MALE",
            training_years=req.athlete.training_years if req.athlete.training_years is not None else 10,
            discipline=req.athlete.discipline or "ENDURANCE",
        )
        profiler = MetabolicProfiler(weight=req.athlete.weight_kg, context=ctx)
        mmp = {int(k): float(v) for k, v in req.mmp.items()}
        return profiler.generate_metabolic_snapshot(mmp)
