"""Persistence for versioned athlete metabolic profiles."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore


@runtime_checkable
class MetabolicProfileStore(Protocol):
    def load_latest_active_profile(self, athlete_id: str) -> Optional[Dict[str, Any]]: ...

    def get_next_profile_version(self, athlete_id: str) -> int: ...

    def deactivate_previous_profiles(self, athlete_id: str) -> None: ...

    def save_metabolic_profile_version(
        self,
        *,
        athlete_id: str,
        profile_version: int,
        profile: Dict[str, Any],
        source_mmp: Dict[str, Any],
        is_active: bool,
        creation_reason: str,
    ) -> Dict[str, Any]: ...

    def update_athlete_current_profile(
        self,
        *,
        athlete_id: str,
        active_profile_id: str,
        profile_version: int,
        profile_status: str,
        confidence_score: float,
        confidence_tier: str,
    ) -> Dict[str, Any]: ...

    def load_current_profile_view(self, athlete_id: str) -> Optional[Dict[str, Any]]: ...


@dataclass
class InMemoryMetabolicProfileStore:
    versions: List[Dict[str, Any]] = field(default_factory=list)
    current: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def load_latest_active_profile(self, athlete_id: str) -> Optional[Dict[str, Any]]:
        active = [v for v in self.versions if v.get("athlete_id") == athlete_id and v.get("is_active")]
        if not active:
            return None
        return dict(sorted(active, key=lambda r: int(r.get("profile_version") or 0))[-1])

    def get_next_profile_version(self, athlete_id: str) -> int:
        existing = [int(v.get("profile_version") or 0) for v in self.versions if v.get("athlete_id") == athlete_id]
        return (max(existing) if existing else 0) + 1

    def deactivate_previous_profiles(self, athlete_id: str) -> None:
        for row in self.versions:
            if row.get("athlete_id") == athlete_id:
                row["is_active"] = False

    def save_metabolic_profile_version(
        self,
        *,
        athlete_id: str,
        profile_version: int,
        profile: Dict[str, Any],
        source_mmp: Dict[str, Any],
        is_active: bool,
        creation_reason: str,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        record = {
            "id": str(uuid.uuid4()),
            "athlete_id": athlete_id,
            "profile_version": profile_version,
            "vo2max_ml_kg_min": profile.get("vo2max_ml_kg_min"),
            "vlamax_mmol_l_s": profile.get("vlamax_mmol_l_s"),
            "mlss_power_w": profile.get("mlss_power_w"),
            "fatmax_power_w": profile.get("fatmax_power_w"),
            "map_power_w": profile.get("map_power_w"),
            "apr_w": profile.get("apr_w"),
            "phenotype_description": profile.get("phenotype_description"),
            "phenotype_type": profile.get("phenotype_type"),
            "confidence_score": profile.get("confidence_score"),
            "confidence_tier": profile.get("confidence_tier"),
            "profile_status": profile.get("profile_status"),
            "is_active": is_active,
            "source_mmp_curve_json": source_mmp.get("mmp_curve_json") or [],
            "source_mmp_status": source_mmp.get("mmp_status"),
            "source_coverage_score": source_mmp.get("coverage_score"),
            "n_activities_included": source_mmp.get("n_activities_included") or 0,
            "n_key_durations_covered": source_mmp.get("n_key_durations_covered") or 0,
            "covered_duration_families": source_mmp.get("duration_families_covered") or {},
            "missing_duration_families": source_mmp.get("missing_duration_families") or [],
            "creation_reason": creation_reason,
            "calculated_at": now,
            "valid_from_date": date.today().isoformat(),
            "created_at": now,
            "updated_at": now,
        }
        self.versions.append(record)
        return dict(record)

    def update_athlete_current_profile(
        self,
        *,
        athlete_id: str,
        active_profile_id: str,
        profile_version: int,
        profile_status: str,
        confidence_score: float,
        confidence_tier: str,
    ) -> Dict[str, Any]:
        row = {
            "athlete_id": athlete_id,
            "active_profile_id": active_profile_id,
            "profile_version": profile_version,
            "profile_status": profile_status,
            "confidence_score": confidence_score,
            "confidence_tier": confidence_tier,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.current[athlete_id] = row
        return dict(row)

    def load_current_profile_view(self, athlete_id: str) -> Optional[Dict[str, Any]]:
        current = self.current.get(athlete_id)
        if not current:
            return None
        active_id = current.get("active_profile_id")
        version = next((v for v in self.versions if v.get("id") == active_id), None)
        if not version:
            return None
        return {**version, **current}


class SupabaseMetabolicProfileStore:
    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        service_role_key: Optional[str] = None,
        timeout_s: float = 30.0,
    ) -> None:
        if httpx is None:  # pragma: no cover
            raise RuntimeError("httpx is required for SupabaseMetabolicProfileStore")
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

    def load_latest_active_profile(self, athlete_id: str) -> Optional[Dict[str, Any]]:
        data = self._request(
            "GET",
            "/athlete_metabolic_profile_versions",
            params={
                "athlete_id": f"eq.{athlete_id}",
                "is_active": "eq.true",
                "order": "profile_version.desc",
                "limit": "1",
            },
        )
        if not data:
            return None
        return dict(data[0])

    def get_next_profile_version(self, athlete_id: str) -> int:
        data = self._request(
            "GET",
            "/athlete_metabolic_profile_versions",
            params={
                "athlete_id": f"eq.{athlete_id}",
                "select": "profile_version",
                "order": "profile_version.desc",
                "limit": "1",
            },
        )
        if not data:
            return 1
        return int(data[0]["profile_version"]) + 1

    def deactivate_previous_profiles(self, athlete_id: str) -> None:
        self._request(
            "PATCH",
            "/athlete_metabolic_profile_versions",
            params={"athlete_id": f"eq.{athlete_id}", "is_active": "eq.true"},
            json={"is_active": False, "updated_at": datetime.now(timezone.utc).isoformat()},
        )

    def save_metabolic_profile_version(
        self,
        *,
        athlete_id: str,
        profile_version: int,
        profile: Dict[str, Any],
        source_mmp: Dict[str, Any],
        is_active: bool,
        creation_reason: str,
    ) -> Dict[str, Any]:
        payload = {
            "athlete_id": athlete_id,
            "profile_version": profile_version,
            "vo2max_ml_kg_min": profile.get("vo2max_ml_kg_min"),
            "vlamax_mmol_l_s": profile.get("vlamax_mmol_l_s"),
            "mlss_power_w": profile.get("mlss_power_w"),
            "fatmax_power_w": profile.get("fatmax_power_w"),
            "map_power_w": profile.get("map_power_w"),
            "apr_w": profile.get("apr_w"),
            "phenotype_description": profile.get("phenotype_description"),
            "phenotype_type": profile.get("phenotype_type"),
            "confidence_score": profile.get("confidence_score"),
            "confidence_tier": profile.get("confidence_tier"),
            "profile_status": profile.get("profile_status"),
            "is_active": is_active,
            "source_mmp_curve_json": source_mmp.get("mmp_curve_json") or [],
            "source_mmp_status": source_mmp.get("mmp_status"),
            "source_coverage_score": source_mmp.get("coverage_score"),
            "n_activities_included": source_mmp.get("n_activities_included") or 0,
            "n_key_durations_covered": source_mmp.get("n_key_durations_covered") or 0,
            "covered_duration_families": source_mmp.get("duration_families_covered") or {},
            "missing_duration_families": source_mmp.get("missing_duration_families") or [],
            "creation_reason": creation_reason,
            "valid_from_date": date.today().isoformat(),
        }
        data = self._request("POST", "/athlete_metabolic_profile_versions", json=payload)
        if isinstance(data, list) and data:
            return dict(data[0])
        return dict(data or payload)

    def update_athlete_current_profile(
        self,
        *,
        athlete_id: str,
        active_profile_id: str,
        profile_version: int,
        profile_status: str,
        confidence_score: float,
        confidence_tier: str,
    ) -> Dict[str, Any]:
        payload = {
            "athlete_id": athlete_id,
            "active_profile_id": active_profile_id,
            "profile_version": profile_version,
            "profile_status": profile_status,
            "confidence_score": confidence_score,
            "confidence_tier": confidence_tier,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        data = self._request(
            "POST",
            "/athlete_current_profile",
            json=payload,
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
            params={"on_conflict": "athlete_id"},
        )
        if isinstance(data, list) and data:
            return dict(data[0])
        return dict(data or payload)

    def load_current_profile_view(self, athlete_id: str) -> Optional[Dict[str, Any]]:
        data = self._request(
            "GET",
            "/athlete_current_profile",
            params={
                "athlete_id": f"eq.{athlete_id}",
                "select": "*,athlete_metabolic_profile_versions(*)",
                "limit": "1",
            },
        )
        if not data:
            return None
        row = data[0]
        nested = row.get("athlete_metabolic_profile_versions")
        if isinstance(nested, list) and nested:
            return {**nested[0], **row}
        return dict(row)


def metabolic_profile_store_from_env() -> MetabolicProfileStore:
    if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
        return SupabaseMetabolicProfileStore()
    return InMemoryMetabolicProfileStore()
