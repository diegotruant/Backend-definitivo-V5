"""Persistence for versioned athlete training thresholds."""

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
class ThresholdStore(Protocol):
    def load_latest_active_thresholds(self, athlete_id: str) -> Optional[Dict[str, Any]]: ...

    def get_next_threshold_version(self, athlete_id: str) -> int: ...

    def deactivate_previous_thresholds(self, athlete_id: str) -> None: ...

    def save_threshold_version(
        self,
        *,
        athlete_id: str,
        threshold_version: int,
        thresholds: Dict[str, Any],
        source_mmp: Dict[str, Any],
        metabolic_profile_version: Optional[int],
        is_active: bool,
        creation_reason: str,
    ) -> Dict[str, Any]: ...

    def update_athlete_current_thresholds(
        self,
        *,
        athlete_id: str,
        active_threshold_id: str,
        threshold_version: int,
        ftp_w: Optional[float],
        lthr_bpm: Optional[float],
        cp_w: Optional[float],
    ) -> Dict[str, Any]: ...

    def load_current_thresholds_view(self, athlete_id: str) -> Optional[Dict[str, Any]]: ...


@dataclass
class InMemoryThresholdStore:
    versions: List[Dict[str, Any]] = field(default_factory=list)
    current: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def load_latest_active_thresholds(self, athlete_id: str) -> Optional[Dict[str, Any]]:
        active = [v for v in self.versions if v.get("athlete_id") == athlete_id and v.get("is_active")]
        if not active:
            return None
        return dict(sorted(active, key=lambda r: int(r.get("threshold_version") or 0))[-1])

    def get_next_threshold_version(self, athlete_id: str) -> int:
        existing = [int(v.get("threshold_version") or 0) for v in self.versions if v.get("athlete_id") == athlete_id]
        return (max(existing) if existing else 0) + 1

    def deactivate_previous_thresholds(self, athlete_id: str) -> None:
        for row in self.versions:
            if row.get("athlete_id") == athlete_id:
                row["is_active"] = False

    def save_threshold_version(
        self,
        *,
        athlete_id: str,
        threshold_version: int,
        thresholds: Dict[str, Any],
        source_mmp: Dict[str, Any],
        metabolic_profile_version: Optional[int],
        is_active: bool,
        creation_reason: str,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        record = {
            "id": str(uuid.uuid4()),
            "athlete_id": athlete_id,
            "threshold_version": threshold_version,
            "ftp_w": thresholds.get("ftp_w"),
            "lthr_bpm": thresholds.get("lthr_bpm"),
            "cp_w": thresholds.get("cp_w"),
            "w_prime_j": thresholds.get("w_prime_j"),
            "map_power_w": thresholds.get("map_power_w"),
            "mlss_power_w": thresholds.get("mlss_power_w"),
            "source_type": thresholds.get("source_type"),
            "source_mmp_status": source_mmp.get("mmp_status"),
            "source_metabolic_profile_version": metabolic_profile_version,
            "is_active": is_active,
            "creation_reason": creation_reason,
            "calculated_at": now,
            "valid_from_date": date.today().isoformat(),
            "created_at": now,
            "updated_at": now,
        }
        self.versions.append(record)
        return dict(record)

    def update_athlete_current_thresholds(
        self,
        *,
        athlete_id: str,
        active_threshold_id: str,
        threshold_version: int,
        ftp_w: Optional[float],
        lthr_bpm: Optional[float],
        cp_w: Optional[float],
    ) -> Dict[str, Any]:
        row = {
            "athlete_id": athlete_id,
            "active_threshold_id": active_threshold_id,
            "threshold_version": threshold_version,
            "ftp_w": ftp_w,
            "lthr_bpm": lthr_bpm,
            "cp_w": cp_w,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.current[athlete_id] = row
        return dict(row)

    def load_current_thresholds_view(self, athlete_id: str) -> Optional[Dict[str, Any]]:
        current = self.current.get(athlete_id)
        if not current:
            return None
        active_id = current.get("active_threshold_id")
        version = next((v for v in self.versions if v.get("id") == active_id), None)
        if not version:
            return None
        return {**version, **current}


class SupabaseThresholdStore:
    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        service_role_key: Optional[str] = None,
        timeout_s: float = 30.0,
    ) -> None:
        if httpx is None:  # pragma: no cover
            raise RuntimeError("httpx is required for SupabaseThresholdStore")
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

    def load_latest_active_thresholds(self, athlete_id: str) -> Optional[Dict[str, Any]]:
        data = self._request(
            "GET",
            "/athlete_threshold_versions",
            params={
                "athlete_id": f"eq.{athlete_id}",
                "is_active": "eq.true",
                "order": "threshold_version.desc",
                "limit": "1",
            },
        )
        return dict(data[0]) if data else None

    def get_next_threshold_version(self, athlete_id: str) -> int:
        data = self._request(
            "GET",
            "/athlete_threshold_versions",
            params={
                "athlete_id": f"eq.{athlete_id}",
                "select": "threshold_version",
                "order": "threshold_version.desc",
                "limit": "1",
            },
        )
        return int(data[0]["threshold_version"]) + 1 if data else 1

    def deactivate_previous_thresholds(self, athlete_id: str) -> None:
        self._request(
            "PATCH",
            "/athlete_threshold_versions",
            params={"athlete_id": f"eq.{athlete_id}", "is_active": "eq.true"},
            json={"is_active": False, "updated_at": datetime.now(timezone.utc).isoformat()},
        )

    def save_threshold_version(
        self,
        *,
        athlete_id: str,
        threshold_version: int,
        thresholds: Dict[str, Any],
        source_mmp: Dict[str, Any],
        metabolic_profile_version: Optional[int],
        is_active: bool,
        creation_reason: str,
    ) -> Dict[str, Any]:
        payload = {
            "athlete_id": athlete_id,
            "threshold_version": threshold_version,
            "ftp_w": thresholds.get("ftp_w"),
            "lthr_bpm": thresholds.get("lthr_bpm"),
            "cp_w": thresholds.get("cp_w"),
            "w_prime_j": thresholds.get("w_prime_j"),
            "map_power_w": thresholds.get("map_power_w"),
            "mlss_power_w": thresholds.get("mlss_power_w"),
            "source_type": thresholds.get("source_type"),
            "source_mmp_status": source_mmp.get("mmp_status"),
            "source_metabolic_profile_version": metabolic_profile_version,
            "is_active": is_active,
            "creation_reason": creation_reason,
            "valid_from_date": date.today().isoformat(),
        }
        data = self._request("POST", "/athlete_threshold_versions", json=payload)
        return dict(data[0]) if isinstance(data, list) and data else dict(data or payload)

    def update_athlete_current_thresholds(
        self,
        *,
        athlete_id: str,
        active_threshold_id: str,
        threshold_version: int,
        ftp_w: Optional[float],
        lthr_bpm: Optional[float],
        cp_w: Optional[float],
    ) -> Dict[str, Any]:
        payload = {
            "athlete_id": athlete_id,
            "active_threshold_id": active_threshold_id,
            "threshold_version": threshold_version,
            "ftp_w": ftp_w,
            "lthr_bpm": lthr_bpm,
            "cp_w": cp_w,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        data = self._request(
            "POST",
            "/athlete_current_thresholds",
            json=payload,
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
            params={"on_conflict": "athlete_id"},
        )
        return dict(data[0]) if isinstance(data, list) and data else dict(data or payload)

    def load_current_thresholds_view(self, athlete_id: str) -> Optional[Dict[str, Any]]:
        data = self._request(
            "GET",
            "/athlete_current_thresholds",
            params={
                "athlete_id": f"eq.{athlete_id}",
                "select": "*,athlete_threshold_versions(*)",
                "limit": "1",
            },
        )
        if not data:
            return None
        row = data[0]
        nested = row.get("athlete_threshold_versions")
        if isinstance(nested, list) and nested:
            return {**nested[0], **row}
        return dict(row)


def threshold_store_from_env() -> ThresholdStore:
    if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
        return SupabaseThresholdStore()
    return InMemoryThresholdStore()
