from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import get_load_service
from api.helpers import json_response
from api.schemas import ManualLoadRequest
from api.services.load_service import LoadService

router = APIRouter(tags=["load"])


@router.post("/load/manual")
def manual_load(
    req: ManualLoadRequest,
    service: LoadService = Depends(get_load_service),
):
    return json_response(service.calculate_manual(req))
