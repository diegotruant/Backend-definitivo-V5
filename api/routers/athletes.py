from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import get_metabolic_profile_service, get_metabolic_profile_store, get_mmp_aggregate_store
from api.helpers import json_response
from api.responses import EnginePayload
from api.route_docs import ERRORS, JSON_OBJECT
from api.services.metabolic_profile_service import MetabolicProfileService

router = APIRouter(prefix="/athletes", tags=["athletes"])


@router.get(
    "/{athlete_id}/metabolic-profile/current",
    summary="Active athlete metabolic profile",
    description=(
        "Return the single active versioned metabolic profile for an athlete. "
        "Profiles are computed only from published aggregate MMP, not per-activity snapshots."
    ),
    operation_id="athletesMetabolicProfileCurrent",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT, 404: ERRORS.get(404, JSON_OBJECT)},
)
def get_current_metabolic_profile(
    athlete_id: str,
    service: MetabolicProfileService = Depends(get_metabolic_profile_service),
    profile_store=Depends(get_metabolic_profile_store),
    mmp_store=Depends(get_mmp_aggregate_store),
):
    return json_response(
        service.get_current_profile(
            athlete_id,
            profile_store=profile_store,
            mmp_store=mmp_store,
        )
    )
