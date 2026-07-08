"""Application service wrapper for athlete MMP aggregation."""

from __future__ import annotations

from engines.persistence.mmp_aggregate_pipeline import sync_athlete_mmp_after_bundle


class MmpAggregateService:
    sync_after_bundle = staticmethod(sync_athlete_mmp_after_bundle)
