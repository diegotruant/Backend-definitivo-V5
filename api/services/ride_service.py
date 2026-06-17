from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional

import numpy as np

from api.errors import ServiceError
from api.schemas import AthleteParams, UpdateProfileRequest
from engines.core.athlete_context import AthleteContext
from engines.core.athlete_physiological_prior import MeasuredProfile
from engines.io.fit_parse_report import build_fit_parse_report
from engines.io.fit_parser import FIT_PARSER_VERSION
from engines.io.workout_summary import build_workout_summary
from engines.io.activity_intelligence import build_activity_intelligence
from engines.io.data_quality_report import build_data_quality_report
from engines.performance.mader_durability import compute_session_durability
from engines.performance.mmp_aggregator import update_power_curve


class RideService:
    def ingest(
        self,
        *,
        stream: Any,
        ride_date: date,
        file_id: str,
        weight_kg: float,
        stored_curve: Optional[Dict[str, Any]],
        file_hash: Optional[str] = None,
    ) -> Dict[str, Any]:
        n_samples = int(getattr(stream, "n_samples", 0) or len(getattr(stream, "power", [])))
        power = [float(p or 0.0) for p in stream.power[:n_samples]]
        hr_stream = None
        if getattr(stream, "has_heart_rate", False):
            hr_stream = [float(h or 0.0) for h in stream.heart_rate[:n_samples]]
        cadence_stream = None
        cadence = getattr(stream, "cadence", None)
        if cadence is not None and bool(np.any(cadence[:n_samples] > 0)):
            cadence_stream = [float(c or 0.0) for c in cadence[:n_samples]]

        quality = build_data_quality_report(stream)
        reliability = float(quality.get("overall_score", 1.0))

        result = update_power_curve(
            power,
            ride_date,
            stored_curve=stored_curve,
            ride_id=file_id,
            weight_kg=weight_kg,
            hr_stream=hr_stream,
            cadence_stream=cadence_stream,
            reliability=reliability,
        )
        return {
            "curve": result.curve,
            "mmp_for_profiler": result.mmp_for_profiler,
            "improvements": len(result.improvements) if result.improvements else 0,
            "ride_usable": result.ride_usable,
            "profile_should_refresh": result.profile_should_refresh,
            "notes": result.notes,
            "file_hash": file_hash,
            "parser_version": FIT_PARSER_VERSION,
            "data_quality_score": round(reliability, 3),
            "available_signals": quality.get("available_signals", []),
            "laps": list(getattr(stream, "laps", []) or []),
        }

    def build_parse_report(self, parsed_upload: Dict[str, Any]) -> Dict[str, Any]:
        stream = parsed_upload.get("_stream")
        if stream is None:
            raise ServiceError("Parsed upload is missing activity stream.", status_code=400, code="INVALID_UPLOAD")
        return build_fit_parse_report(
            stream=stream,
            file_id=str(parsed_upload.get("file_id") or "upload.fit"),
            file_hash=parsed_upload.get("file_hash"),
        )

    def update_profile(self, req: UpdateProfileRequest) -> Dict[str, Any]:
        from engines.io.profile_anchor_flow import update_profile_from_ride

        ctx = self._context_from_athlete(req.athlete)
        anchor_data = req.anchor
        anchor = MeasuredProfile(
            measured_on=anchor_data.get("measured_on", req.as_of),
            vo2max=anchor_data.get("vo2max"),
            mlss_watts=anchor_data.get("mlss_watts"),
            vlamax=anchor_data.get("vlamax"),
            source=anchor_data.get("source", "field_test"),
        )
        ride_mmp = {int(k): float(v) for k, v in req.ride_mmp.items()}
        return update_profile_from_ride(
            anchor,
            ride_mmp,
            weight_kg=req.athlete.weight_kg,
            as_of=req.as_of,
            load_factor=req.load_factor,
            context=ctx,
        )

    def build_summary(
        self,
        stream: Any,
        *,
        weight_kg: float,
        ftp: Optional[float],
        lthr: Optional[float],
        athlete: AthleteParams,
        metabolic_snapshot: Optional[Dict[str, Any]],
        hrv_step_seconds: Optional[float],
        hrv_max_windows: int,
    ) -> Dict[str, Any]:
        ctx = self._context_from_athlete(athlete)
        return build_workout_summary(
            stream,
            weight_kg=weight_kg,
            ftp=ftp,
            lthr=lthr,
            context=ctx,
            metabolic_snapshot=metabolic_snapshot,
            hrv_step_seconds=hrv_step_seconds,
            hrv_max_windows=hrv_max_windows,
        )

    def build_intelligence(
        self,
        stream: Any,
        *,
        weight_kg: float,
        ftp: Optional[float] = None,
        cp: Optional[float] = None,
        lthr: Optional[float] = None,
    ) -> Dict[str, Any]:
        return build_activity_intelligence(stream, weight_kg=weight_kg, ftp=ftp, cp=cp, lthr=lthr)

    def build_data_quality(self, stream: Any) -> Dict[str, Any]:
        return build_data_quality_report(stream)

    def compute_durability(
        self,
        stream: Any,
        *,
        weight_kg: float,
        metabolic_snapshot: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not metabolic_snapshot or metabolic_snapshot.get("status") != "success":
            raise ServiceError(
                "metabolic_snapshot_json must be a successful generate_metabolic_snapshot() payload.",
                status_code=400,
                code="INVALID_SNAPSHOT",
            )
        if not getattr(stream, "has_power", False):
            raise ServiceError("Activity has no power data.", status_code=422, code="NO_POWER")
        power = [
            float(p or 0.0)
            for p in stream.power[: getattr(stream, "n_samples", len(stream.power))]
        ]
        return compute_session_durability(power, metabolic_snapshot, weight_kg=weight_kg)

    @staticmethod
    def _context_from_athlete(athlete: AthleteParams) -> AthleteContext:
        return AthleteContext(
            gender=athlete.gender or "MALE",
            training_years=athlete.training_years if athlete.training_years is not None else 10,
            discipline=athlete.discipline or "ENDURANCE",
        )
