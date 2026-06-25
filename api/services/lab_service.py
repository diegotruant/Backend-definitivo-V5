from __future__ import annotations

from datetime import date
from typing import Any, Dict

from api.engine_schemas import (
    LabResultValidateRequest,
    LabTextParseRequest,
    LactateThresholdsRequest,
    LactateValidateModelRequest,
    VlapeakObservedRequest,
    VlapeakValidateRequest,
)
from api.services.engine_context import mmp_dict, profiler_from_athlete
from engines.metabolic.glycolytic_validation_engine import (
    compute_vlapeak_observed,
    validate_vlapeak_against_model,
)
from engines.metabolic.lab_data import create_lab_result, parse_lab_text, validate_lab_result
from engines.metabolic.lactate_validation_engine import (
    LactateStep,
    compute_lactate_thresholds,
    validate_model_against_lactate,
)


class LabService:
    def parse_text(self, req: LabTextParseRequest) -> Dict[str, Any]:
        result = parse_lab_text(req.text)
        return result.to_dict()

    def validate_result(self, req: LabResultValidateRequest) -> Dict[str, Any]:
        from engines.metabolic.lab_data import LabTestResult

        result = LabTestResult.from_dict(req.lab_result)
        warnings = validate_lab_result(result)
        return {"status": "success", "warnings": warnings, "valid": len(warnings) == 0}

    def create_result(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raw_date = payload.pop("test_date", None) or date.today().isoformat()
        test_date = date.fromisoformat(str(raw_date).split("T")[0])
        result = create_lab_result(test_date=test_date, **payload)
        return result.to_dict() if hasattr(result, "to_dict") else dict(result)

    def lactate_thresholds(self, req: LactateThresholdsRequest) -> Dict[str, Any]:
        steps = [
            LactateStep(
                power_w=s.power_w,
                lactate_mmol=s.lactate_mmol,
                hr_mean=s.hr_mean,
                cadence_mean=s.cadence_mean,
                duration_s=s.duration_s,
            )
            for s in req.steps
        ]
        thresholds = compute_lactate_thresholds(steps)
        return {"status": "success", "thresholds": thresholds.to_dict()}

    def validate_lactate_model(self, req: LactateValidateModelRequest) -> Dict[str, Any]:
        profiler = profiler_from_athlete(req.athlete)
        steps = [
            LactateStep(
                power_w=s.power_w,
                lactate_mmol=s.lactate_mmol,
                hr_mean=s.hr_mean,
                cadence_mean=s.cadence_mean,
                duration_s=s.duration_s,
            )
            for s in req.steps
        ]
        return validate_model_against_lactate(
            steps,
            profiler,
            mmp_dict(req.mmp),
            expected_eta=req.expected_eta,
        )

    def vlapeak_observed(self, req: VlapeakObservedRequest) -> Dict[str, Any]:
        return compute_vlapeak_observed(
            req.lactate_pre_mmol,
            req.lactate_post_mmol,
            req.duration_s,
        )

    def validate_vlapeak(self, req: VlapeakValidateRequest) -> Dict[str, Any]:
        return validate_vlapeak_against_model(
            vlapeak_observed_mmol_l_s=req.vlapeak_observed_mmol_l_s,
            predicted_vlapeak_mmol_l_s=req.predicted_vlapeak_mmol_l_s,
            model_vlamax_mmol_l_s=req.model_vlamax_mmol_l_s,
        )
