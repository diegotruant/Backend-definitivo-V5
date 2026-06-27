"""Extended profile/metabolic engine endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import get_profile_extended_service
from api.engine_schemas import (
    BayesianSnapshotRequest,
    CrossValidateRequest,
    CtlAtlTsbRequest,
    DetrainingApplyRequest,
    FatmaxCompareRequest,
    FatmaxLabRequest,
    FatmaxReportRequest,
    GlycolyticProfileRequest,
    KalmanTrajectoryRequest,
    MetabolicCurrentRequest,
    MmpAthleteRequest,
    MmpQualityRequest,
    SegmentedSnapshotRequest,
    VlamaxPowerSeriesRequest,
    VlamaxSprintRequest,
    WPrimeTauRequest,
)
from api.helpers import json_response
from api.responses import EnginePayload
from api.route_docs import ERRORS, JSON_OBJECT
from api.services.profile_extended_service import ProfileExtendedService

router = APIRouter(prefix="/profile", tags=["profile"])


@router.post("/snapshot/segmented", operation_id="profileSnapshotSegmented", response_model=EnginePayload, responses={200: JSON_OBJECT})
def snapshot_segmented(req: SegmentedSnapshotRequest, service: ProfileExtendedService = Depends(get_profile_extended_service)):
    return json_response(service.segmented_snapshot(req))


@router.post("/snapshot/auto", operation_id="profileSnapshotAuto", response_model=EnginePayload, responses={200: JSON_OBJECT})
def snapshot_auto(req: MmpAthleteRequest, service: ProfileExtendedService = Depends(get_profile_extended_service)):
    return json_response(service.auto_snapshot(req))


@router.post("/snapshot/bayesian", operation_id="profileSnapshotBayesian", response_model=EnginePayload, responses={200: JSON_OBJECT})
def snapshot_bayesian(req: BayesianSnapshotRequest, service: ProfileExtendedService = Depends(get_profile_extended_service)):
    return json_response(service.bayesian_snapshot(req))


@router.post("/vlamax-from-sprint", operation_id="profileVlamaxFromSprint", response_model=EnginePayload, responses={200: JSON_OBJECT})
def vlamax_from_sprint(req: VlamaxSprintRequest, service: ProfileExtendedService = Depends(get_profile_extended_service)):
    return json_response(service.vlamax_from_sprint(req))


@router.post(
    "/vlamax-from-power-series",
    operation_id="profileVlamaxFromPowerSeries",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT, 400: ERRORS[400]},
)
def vlamax_from_power_series(
    req: VlamaxPowerSeriesRequest,
    service: ProfileExtendedService = Depends(get_profile_extended_service),
):
    return json_response(service.vlamax_from_power_series(req))


@router.post(
    "/fatmax/report",
    operation_id="profileFatmaxReport",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT},
)
def fatmax_report(
    req: FatmaxReportRequest,
    service: ProfileExtendedService = Depends(get_profile_extended_service),
):
    return json_response(service.fatmax_report(req))  # type: ignore[attr-defined]


@router.post(
    "/fatmax/lab",
    operation_id="profileFatmaxLab",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT},
)
def fatmax_lab(
    req: FatmaxLabRequest,
    service: ProfileExtendedService = Depends(get_profile_extended_service),
):
    return json_response(service.fatmax_lab(req))  # type: ignore[attr-defined]


@router.post(
    "/fatmax/compare",
    operation_id="profileFatmaxCompare",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT},
)
def fatmax_compare(
    req: FatmaxCompareRequest,
    service: ProfileExtendedService = Depends(get_profile_extended_service),
):
    return json_response(service.fatmax_compare(req))  # type: ignore[attr-defined]


@router.post("/kalman/trajectory", operation_id="profileKalmanTrajectory", response_model=EnginePayload, responses={200: JSON_OBJECT})
def kalman_trajectory(req: KalmanTrajectoryRequest, service: ProfileExtendedService = Depends(get_profile_extended_service)):
    return json_response(service.kalman_trajectory(req))


@router.post("/metabolic/current", operation_id="profileMetabolicCurrent", response_model=EnginePayload, responses={200: JSON_OBJECT})
def metabolic_current(req: MetabolicCurrentRequest, service: ProfileExtendedService = Depends(get_profile_extended_service)):
    return json_response(service.metabolic_current(req))


@router.post("/detraining/apply", operation_id="profileDetrainingApply", response_model=EnginePayload, responses={200: JSON_OBJECT})
def detraining_apply(req: DetrainingApplyRequest, service: ProfileExtendedService = Depends(get_profile_extended_service)):
    return json_response(service.apply_detraining(req))


@router.post("/training-load/ctl-atl-tsb", operation_id="profileCtlAtlTsb", response_model=EnginePayload, responses={200: JSON_OBJECT})
def ctl_atl_tsb(req: CtlAtlTsbRequest, service: ProfileExtendedService = Depends(get_profile_extended_service)):
    return json_response(service.ctl_atl_tsb(req.tss_history))


@router.post("/cross-validate", operation_id="profileCrossValidate", response_model=EnginePayload, responses={200: JSON_OBJECT})
def cross_validate(req: CrossValidateRequest, service: ProfileExtendedService = Depends(get_profile_extended_service)):
    return json_response(service.cross_validate(req))


@router.post("/mmp-quality", operation_id="profileMmpQuality", response_model=EnginePayload, responses={200: JSON_OBJECT})
def mmp_quality(req: MmpQualityRequest, service: ProfileExtendedService = Depends(get_profile_extended_service)):
    return json_response(service.mmp_quality(req))


@router.post("/snapshot/phenotype", operation_id="profileSnapshotPhenotype", response_model=EnginePayload, responses={200: JSON_OBJECT})
def snapshot_phenotype(req: GlycolyticProfileRequest, service: ProfileExtendedService = Depends(get_profile_extended_service)):
    return json_response(service.phenotype_enhance(req))


@router.post("/glycolytic-profile", operation_id="profileGlycolyticProfile", response_model=EnginePayload, responses={200: JSON_OBJECT})
def glycolytic_profile(req: GlycolyticProfileRequest, service: ProfileExtendedService = Depends(get_profile_extended_service)):
    return json_response(service.glycolytic_profile(req))


@router.post("/w-prime/tau", operation_id="profileWPrimeTau", response_model=EnginePayload, responses={200: JSON_OBJECT})
def w_prime_tau(
    req: WPrimeTauRequest,
    service: ProfileExtendedService = Depends(get_profile_extended_service),
):
    return json_response(service.w_prime_tau(req.tau_model, req.athlete_profile))
