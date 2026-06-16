"""Generic integration helpers without vendor-specific assumptions."""

from .activity_normalizer import normalize_external_activity, deduplicate_activities

__all__ = ["normalize_external_activity", "deduplicate_activities"]
