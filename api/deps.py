"""FastAPI dependency injection for application services."""

from __future__ import annotations

from functools import lru_cache
from api.services import (
    LoadService,
    HistoryService,
    PlanningService,
    ReadinessService,
    PerformanceService,
    ProfileService,
    RideService,
    TeamService,
    TestService,
    TwinService,
    WorkoutService,
)


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
def get_history_service() -> HistoryService:
    return HistoryService()


@lru_cache
def get_readiness_service() -> ReadinessService:
    return ReadinessService()


@lru_cache
def get_planning_service() -> PlanningService:
    return PlanningService()
