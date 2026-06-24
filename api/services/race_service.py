from __future__ import annotations

from typing import Any, Dict

from api.engine_schemas import RaceGpxAnalyzeRequest, RaceGpxSimulateRequest
from engines.performance.race_prediction_engine import (
    analyze_course,
    build_course_segments,
    detect_climbs,
    parse_gpx_course,
    simulate_gpx_race,
)


class RaceService:
    def analyze_gpx(self, req: RaceGpxAnalyzeRequest) -> Dict[str, Any]:
        points = parse_gpx_course(req.gpx_text)
        course = analyze_course(points)
        segments = build_course_segments(points)
        climbs = detect_climbs(points)
        return {
            "status": "success",
            "course": course,
            "n_segments": len(segments),
            "climbs": climbs,
        }

    def simulate_gpx(self, req: RaceGpxSimulateRequest) -> Dict[str, Any]:
        return simulate_gpx_race(
            req.gpx_text,
            weight_kg=req.weight_kg,
            ftp_w=req.ftp_w,
            metabolic_snapshot=req.metabolic_snapshot,
            bike_weight_kg=req.bike_weight_kg,
        )
