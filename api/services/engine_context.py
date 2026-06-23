"""Shared helpers for building engine contexts from API athlete envelopes."""

from __future__ import annotations

from typing import Any, Dict

from api.schemas import AthleteParams
from engines.core.athlete_context import AthleteContext
from engines.metabolic.metabolic_profiler import MetabolicProfiler


def athlete_context_from_params(athlete: AthleteParams) -> AthleteContext:
    return AthleteContext(
        gender=athlete.gender or "MALE",
        training_years=athlete.training_years if athlete.training_years is not None else 10,
        discipline=athlete.discipline or "ENDURANCE",
    )


def profiler_from_athlete(
    athlete: AthleteParams,
) -> MetabolicProfiler:
    return MetabolicProfiler(
        weight=athlete.weight_kg,
        context=athlete_context_from_params(athlete),
    )


def mmp_dict(raw: Dict[str, float]) -> Dict[int, float]:
    return {int(k): float(v) for k, v in raw.items()}


def power_list(stream: Any) -> list[float]:
    n = int(getattr(stream, "n_samples", 0) or len(getattr(stream, "power", [])))
    return [float(p or 0.0) for p in stream.power[:n]]
