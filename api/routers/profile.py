from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import get_profile_service
from api.helpers import json_response
from api.schemas import SnapshotRequest
from api.services.profile_service import ProfileService

router = APIRouter(prefix="/profile", tags=["profile"])


@router.post("/snapshot")
def snapshot(
    req: SnapshotRequest,
    service: ProfileService = Depends(get_profile_service),
):
    return json_response(service.build_snapshot(req))
