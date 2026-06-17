from __future__ import annotations

from typing import Any, Dict

from api.schemas import AthleteParams, SnapshotRequest
from engines.core.athlete_context import AthleteContext
from engines.core.science_contracts import resolve_w_prime_tau
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
        cadence_status = "measured" if req.effective_cadence_rpm else "unknown"
        snap = profiler.generate_metabolic_snapshot(
            mmp,
            effective_cadence_rpm=req.effective_cadence_rpm,
            cadence_anchor_status=cadence_status,
        )
        if req.tau_model:
            tau_s, model_used = resolve_w_prime_tau(req.tau_model)
            snap["w_prime_tau"] = {
                "tau_s": round(tau_s, 1),
                "tau_model": model_used,
            }
        return snap
