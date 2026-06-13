"""FastAPI dependency injection for application services."""

from __future__ import annotations

from functools import lru_cache

from api.services import (
    LoadService,
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
