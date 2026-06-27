"""Application services — orchestrate engines without HTTP concerns."""

from api.services.explainability_service import ExplainabilityService
from api.services.history_service import HistoryService
from api.services.integration_service import IntegrationService
from api.services.lab_service import LabService
from api.services.load_extended_service import LoadExtendedService
from api.services.load_service import LoadService
from api.services.meta_service import MetaService
from api.services.performance_service import PerformanceService
from api.services.planning_service import PlanningService
from api.services.profile_extended_service import ProfileExtendedService
from api.services.profile_service import ProfileService
from api.services.race_service import RaceService
from api.services.readiness_service import ReadinessService
from api.services.ride_analytics_service import RideAnalyticsService
from api.services.ride_service import RideService
from api.services.team_service import TeamService
from api.services.test_service import TestService
from api.services.twin_service import TwinService
from api.services.workout_service import WorkoutService

# Registers FATmax extension methods on ProfileExtendedService without creating
# a dependency from the core profile service to the new reporting module.
import api.services.fatmax_profile_service as _fatmax_profile_service  # noqa: F401,E402

__all__ = [
    "ExplainabilityService",
    "HistoryService",
    "IntegrationService",
    "LabService",
    "LoadExtendedService",
    "LoadService",
    "MetaService",
    "PerformanceService",
    "PlanningService",
    "ProfileExtendedService",
    "ProfileService",
    "RaceService",
    "ReadinessService",
    "RideAnalyticsService",
    "RideService",
    "TeamService",
    "TestService",
    "TwinService",
    "WorkoutService",
]
