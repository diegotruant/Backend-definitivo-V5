from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> Dict[str, Any]:
    from api.app import app

    return {"status": "ok", "service": "digital-twin-api", "version": app.version}
