"""Persistence adapters for athlete-level MMP aggregation (Supabase / in-memory)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore


@runtime_checkable
class MmpAggregateStore(Protocol):
    """Contract implemented by Supabase worker / platform layer."""

    def insert_activity_mmp_points(
        self,
        *,
        athlete_id: str,
        activity_id: str,
        activity_file_id: str,
        activity_date: str,
        points: List[Dict[str, Any]],
    ) -> int:
        """Persist per-activity MMP rows. Returns number of rows written."""

    def load_aggregate_curve(self, athlete_id: str) -> List[Dict[str, Any]]:
        """Load current aggregate curve JSON list for athlete."""

    def count_distinct_activities(self, athlete_id: str) -> int:
        """Count activities that contributed MMP points."""

    def upsert_aggregate(
        self,
        *,
        athlete_id: str,
        mmp_curve_json: List[Dict[str, Any]],
        coverage_score: float,
        confidence_tier: str,
        mmp_status: str,
        n_activities_included: int,
        n_key_durations_covered: int,
    ) -> Dict[str, Any]:
        """Save aggregate row and return persisted record."""


@dataclass
class InMemoryMmpAggregateStore:
    """Test/dev store — mirrors Supabase tables in process memory."""

    activity_points: List[Dict[str, Any]] = field(default_factory=list)
    aggregates: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def insert_activity_mmp_points(
        self,
        *,
        athlete_id: str,
        activity_id: str,
        activity_file_id: str,
        activity_date: str,
        points: List[Dict[str, Any]],
    ) -> int:
        written = 0
        for point in points:
            self.activity_points.append(
                {
                    "athlete_id": athlete_id,
                    "activity_id": activity_id,
                    "activity_file_id": activity_file_id,
                    "activity_date": activity_date[:10],
                    "duration_s": int(point["duration_s"]),
                    "power_w": float(point["power_w"]),
                }
            )
            written += 1
        return written

    def load_aggregate_curve(self, athlete_id: str) -> List[Dict[str, Any]]:
        row = self.aggregates.get(athlete_id) or {}
        curve = row.get("mmp_curve_json") or []
        return list(curve) if isinstance(curve, list) else []

    def count_distinct_activities(self, athlete_id: str) -> int:
        ids = {
            row["activity_id"]
            for row in self.activity_points
            if row.get("athlete_id") == athlete_id
        }
        return len(ids)

    def upsert_aggregate(
        self,
        *,
        athlete_id: str,
        mmp_curve_json: List[Dict[str, Any]],
        coverage_score: float,
        confidence_tier: str,
        mmp_status: str,
        n_activities_included: int,
        n_key_durations_covered: int,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        existing = self.aggregates.get(athlete_id) or {}
        record = {
            "athlete_id": athlete_id,
            "mmp_curve_json": list(mmp_curve_json),
            "coverage_score": coverage_score,
            "confidence_tier": confidence_tier,
            "mmp_status": mmp_status,
            "n_activities_included": n_activities_included,
            "n_key_durations_covered": n_key_durations_covered,
            "created_at": existing.get("created_at") or now,
            "updated_at": now,
        }
        self.aggregates[athlete_id] = record
        return dict(record)


class SupabaseMmpAggregateStore:
    """
    PostgREST client for ``activity_mmp_points`` and ``athlete_mmp_aggregate``.

    Requires ``SUPABASE_URL`` and ``SUPABASE_SERVICE_ROLE_KEY`` environment variables.
    """

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        service_role_key: Optional[str] = None,
        timeout_s: float = 30.0,
    ) -> None:
        if httpx is None:  # pragma: no cover
            raise RuntimeError("httpx is required for SupabaseMmpAggregateStore")
        self.base_url = (base_url or os.environ.get("SUPABASE_URL", "")).rstrip("/")
        self.service_role_key = service_role_key or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
        if not self.base_url or not self.service_role_key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        self._client = httpx.Client(
            base_url=f"{self.base_url}/rest/v1",
            headers={
                "apikey": self.service_role_key,
                "Authorization": f"Bearer {self.service_role_key}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            },
            timeout=timeout_s,
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._client.request(method, path, **kwargs)
        response.raise_for_status()
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def insert_activity_mmp_points(
        self,
        *,
        athlete_id: str,
        activity_id: str,
        activity_file_id: str,
        activity_date: str,
        points: List[Dict[str, Any]],
    ) -> int:
        if not points:
            return 0
        rows = [
            {
                "athlete_id": athlete_id,
                "activity_id": activity_id,
                "activity_file_id": activity_file_id,
                "activity_date": activity_date[:10],
                "duration_s": int(point["duration_s"]),
                "power_w": float(point["power_w"]),
            }
            for point in points
        ]
        self._request("POST", "/activity_mmp_points", json=rows)
        return len(rows)

    def load_aggregate_curve(self, athlete_id: str) -> List[Dict[str, Any]]:
        data = self._request(
            "GET",
            "/athlete_mmp_aggregate",
            params={
                "athlete_id": f"eq.{athlete_id}",
                "select": "mmp_curve_json",
                "limit": "1",
            },
        )
        if not data:
            return []
        row = data[0] if isinstance(data, list) else data
        curve = (row or {}).get("mmp_curve_json") or []
        return list(curve) if isinstance(curve, list) else []

    def count_distinct_activities(self, athlete_id: str) -> int:
        data = self._request(
            "GET",
            "/activity_mmp_points",
            params={
                "athlete_id": f"eq.{athlete_id}",
                "select": "activity_id",
            },
        )
        if not data:
            return 0
        return len({row["activity_id"] for row in data if row.get("activity_id")})

    def upsert_aggregate(
        self,
        *,
        athlete_id: str,
        mmp_curve_json: List[Dict[str, Any]],
        coverage_score: float,
        confidence_tier: str,
        mmp_status: str,
        n_activities_included: int,
        n_key_durations_covered: int,
    ) -> Dict[str, Any]:
        payload = {
            "athlete_id": athlete_id,
            "mmp_curve_json": mmp_curve_json,
            "coverage_score": coverage_score,
            "confidence_tier": confidence_tier,
            "mmp_status": mmp_status,
            "n_activities_included": n_activities_included,
            "n_key_durations_covered": n_key_durations_covered,
        }
        data = self._request(
            "POST",
            "/athlete_mmp_aggregate",
            json=payload,
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
            params={"on_conflict": "athlete_id"},
        )
        if isinstance(data, list) and data:
            return dict(data[0])
        return dict(data or payload)


def mmp_store_from_env() -> MmpAggregateStore:
    """Factory: Supabase when configured, otherwise in-memory (local dev only)."""
    if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
        return SupabaseMmpAggregateStore()
    return InMemoryMmpAggregateStore()
