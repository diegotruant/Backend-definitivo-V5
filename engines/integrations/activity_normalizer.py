"""Normalize and deduplicate imported activity metadata."""

from __future__ import annotations

from hashlib import sha1
from typing import Any, Dict, List


def normalize_external_activity(payload: Dict[str, Any]) -> Dict[str, Any]:
    start = payload.get("start_time") or payload.get("date") or payload.get("timestamp")
    distance = payload.get("distance_m") or payload.get("distance")
    duration = payload.get("duration_s") or payload.get("elapsed_time") or payload.get("duration")
    source_id = payload.get("source_id") or payload.get("external_id")
    fingerprint = sha1(f"{start}|{distance}|{duration}|{source_id}".encode("utf-8")).hexdigest()
    return {"status": "success", "activity": {"activity_id": source_id or fingerprint[:12], "start_time": start, "distance_m": distance, "duration_s": duration, "fingerprint": fingerprint, "raw": payload}}


def deduplicate_activities(activities: List[Dict[str, Any]]) -> Dict[str, Any]:
    seen = set()
    unique = []
    duplicates = []
    for act in activities:
        norm = normalize_external_activity(act).get("activity", {})
        fp = norm.get("fingerprint")
        if fp in seen:
            duplicates.append(norm)
        else:
            seen.add(fp)
            unique.append(norm)
    return {"status": "success", "unique": unique, "duplicates": duplicates, "duplicate_count": len(duplicates)}
