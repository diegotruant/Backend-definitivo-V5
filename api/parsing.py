"""Request field parsing helpers (dates, snapshots, curves, athlete context)."""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Dict, Optional

from engines.core.athlete_context import AthleteContext

from api.schemas import AthleteParams

try:
    from fastapi import HTTPException
except ImportError:  # pragma: no cover
    raise ImportError("FastAPI is required for the API layer: pip install fastapi uvicorn")


def athlete_context(gender: str, training_years: float, discipline: str) -> AthleteContext:
    return AthleteContext(
        gender=gender or "MALE",
        training_years=training_years if training_years is not None else 10,
        discipline=discipline or "ENDURANCE",
    )


def athlete_context_from_params(athlete: AthleteParams) -> AthleteContext:
    return athlete_context(athlete.gender, athlete.training_years, athlete.discipline)


def parse_metabolic_snapshot(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    try:
        snap = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid metabolic_snapshot_json: {exc}") from exc
    if not isinstance(snap, dict):
        raise HTTPException(status_code=400, detail="metabolic_snapshot_json must be a JSON object.")
    return snap


def parse_iso_date(value: str, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field_name} must be ISO date (YYYY-MM-DD).")


def coerce_stored_curve(stored: Optional[Dict[str, Any]]) -> Optional[Dict[Any, Any]]:
    if not stored:
        return None
    if all(str(k).lstrip("-").isdigit() for k in stored.keys()):
        return {int(k): v for k, v in stored.items()}
    return stored
