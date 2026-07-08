"""FastAPI dependency injection for application services."""

from __future__ import annotations

from functools import lru_cache

from fastapi import Request

from api.auth.principal import Principal
from api.services import (
    CoachService,
    DashboardService,
    ExplainabilityService,
    HistoryService,
    IntegrationService,
    LabService,
    LoadExtendedService,
    LoadService,
    MetaService,
    PerformanceService,
    PlanningService,
    ProfileExtendedService,
    ProfileService,
    RaceService,
    ReadinessService,
    RideAnalyticsService,
    RideService,
    TeamService,
    TestService,
    TwinService,
    WorkoutService,
)
from api.services.mmp_aggregate_service import MmpAggregateService
from engines.persistence.mmp_aggregate_store import MmpAggregateStore, mmp_store_from_env


@lru_cache
def get_coach_service() -> CoachService:
    return CoachService()


@lru_cache
def get_test_service() -> TestService:
    return TestService()


@lru_cache
def get_ride_service() -> RideService:
    return RideService()


@lru_cache
def get_profile_service() -> ProfileService:
    return ProfileService()


@lru_cache
def get_profile_extended_service() -> ProfileExtendedService:
    return ProfileExtendedService()


@lru_cache
def get_workout_service() -> WorkoutService:
    return WorkoutService()


@lru_cache
def get_twin_service() -> TwinService:
    return TwinService()


@lru_cache
def get_team_service() -> TeamService:
    return TeamService()


@lru_cache
def get_performance_service() -> PerformanceService:
    return PerformanceService()


@lru_cache
def get_load_service() -> LoadService:
    return LoadService()


@lru_cache
def get_load_extended_service() -> LoadExtendedService:
    return LoadExtendedService()


@lru_cache
def get_history_service() -> HistoryService:
    return HistoryService()


@lru_cache
def get_readiness_service() -> ReadinessService:
    return ReadinessService()


@lru_cache
def get_planning_service() -> PlanningService:
    return PlanningService()


@lru_cache
def get_lab_service() -> LabService:
    return LabService()


@lru_cache
def get_ride_analytics_service() -> RideAnalyticsService:
    return RideAnalyticsService()


@lru_cache
def get_explainability_service() -> ExplainabilityService:
    return ExplainabilityService()


@lru_cache
def get_race_service() -> RaceService:
    return RaceService()


@lru_cache
def get_integration_service() -> IntegrationService:
    return IntegrationService()


@lru_cache
def get_dashboard_service() -> DashboardService:
    return DashboardService()


@lru_cache
def get_meta_service() -> MetaService:
    return MetaService()


@lru_cache
def get_mmp_aggregate_service() -> MmpAggregateService:
    return MmpAggregateService()


def get_mmp_aggregate_store() -> MmpAggregateStore:
    return mmp_store_from_env()


def get_request_principal(request: Request) -> Principal | None:
    return getattr(request.state, "principal", None)


def get_request_athlete_id(request: Request) -> str | None:
    return getattr(request.state, "athlete_id", None)
