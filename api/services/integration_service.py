from __future__ import annotations

from typing import Any, Dict

from api.engine_schemas import IntegrationDeduplicateRequest, IntegrationNormalizeRequest
from engines.integrations.activity_normalizer import deduplicate_activities, normalize_external_activity


class IntegrationService:
    def normalize_activity(self, req: IntegrationNormalizeRequest) -> Dict[str, Any]:
        return normalize_external_activity(req.activity)

    def deduplicate(self, req: IntegrationDeduplicateRequest) -> Dict[str, Any]:
        return deduplicate_activities(req.activities)
