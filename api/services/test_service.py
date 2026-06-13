from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from api.errors import ServiceError
from api.schemas import AthleteParams, ConfirmRequest, InPersonTestRequest
from engines.core.athlete_context import AthleteContext
from engines.io.profile_anchor_flow import build_anchor_from_proposal
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from engines.performance.effort_extractor import extract_test_proposal
from engines.performance.test_protocols import run_test as run_in_person_test


class TestService:
    def propose_from_files(self, parsed_files: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not parsed_files:
            raise ServiceError("No files uploaded.", status_code=400, code="NO_FILES")
        proposal = extract_test_proposal(parsed_files)
        return proposal.to_dict()

    def confirm(self, req: ConfirmRequest) -> Dict[str, Any]:
        ctx = self._context_from_athlete(req.athlete)
        try:
            measured_on = date.fromisoformat(req.measured_on)
        except ValueError as exc:
            raise ServiceError(
                "measured_on must be ISO date (YYYY-MM-DD).",
                status_code=400,
                code="INVALID_DATE",
            ) from exc
        result = build_anchor_from_proposal(
            req.proposal,
            weight_kg=req.athlete.weight_kg,
            measured_on=measured_on,
            context=ctx,
            active_muscle_mass_kg=req.athlete.active_muscle_mass_kg,
        )
        return result.to_dict()

    def run_in_person(self, req: InPersonTestRequest) -> Dict[str, Any]:
        envelope = req.model_dump()
        athlete = envelope.get("athlete") or {}
        weight = float(athlete.get("weight_kg") or 70.0)
        ctx = AthleteContext(
            gender=str(athlete.get("sex") or athlete.get("gender") or "MALE"),
            training_years=float(athlete.get("training_years") or 10),
            discipline=str(athlete.get("discipline") or "ENDURANCE"),
        )
        profiler = MetabolicProfiler(weight=weight, context=ctx)
        return run_in_person_test(envelope, profiler=profiler)

    @staticmethod
    def _context_from_athlete(athlete: AthleteParams) -> AthleteContext:
        return AthleteContext(
            gender=athlete.gender or "MALE",
            training_years=athlete.training_years if athlete.training_years is not None else 10,
            discipline=athlete.discipline or "ENDURANCE",
        )
