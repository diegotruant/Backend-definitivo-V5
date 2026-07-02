"""Generic integration helpers without vendor-specific assumptions."""

from .activity_normalizer import normalize_external_activity, deduplicate_activities
from .health_daily_normalizer import normalize_health_daily

__all__ = ["normalize_external_activity", "deduplicate_activities", "normalize_health_daily"]
