from __future__ import annotations

from typing import Any, Dict

from api.engine_schemas import RaceGpxAnalyzeRequest, RaceGpxSimulateRequest
from engines.performance.race_prediction_engine import (
    analyze_course,
    build_course_segments,
    parse_gpx_course,
    simulate_gpx_race,
)


class RaceService:
    def analyze_gpx(self, req: RaceGpxAnalyzeRequest) -> Dict[str, Any]:
        from api.errors import ServiceError

        try:
            points = parse_gpx_course(req.gpx_text)
        except ValueError as exc:
            raise ServiceError(str(exc), status_code=422, code="INVALID_GPX") from exc
        course = analyze_course(points)
        segments = build_course_segments(points)
        return {
            "status": "success",
            "course": course,
            "n_segments": len(segments),
            "climbs": course.get("climbs", []),
        }

    def simulate_gpx(self, req: RaceGpxSimulateRequest) -> Dict[str, Any]:
        from api.errors import ServiceError

        try:
            return simulate_gpx_race(
                req.gpx_text,
                weight_kg=req.weight_kg,
                ftp_w=req.ftp_w,
                metabolic_snapshot=req.metabolic_snapshot,
                bike_weight_kg=req.bike_weight_kg,
            )
        except ValueError as exc:
            raise ServiceError(str(exc), status_code=422, code="INVALID_GPX") from exc
