"""
Race Prediction Engine
======================

GPX-based course ingestion and race-performance simulation.

The engine converts a route into distance/elevation/grade segments, detects
climbs, and simulates a coach-facing race plan:

- distance and elevation gain/loss
- climb profile
- predicted race time
- mechanical and metabolic energy demand
- recommended pacing by terrain section

Tier: MODEL. The physics model is transparent and deterministic, but real-world
speed depends on wind, drafting, surface, turns, traffic, equipment, and rider
position, which are only approximated here.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import atan, cos, radians, sin, sqrt
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
import warnings
import xml.etree.ElementTree as ET

try:
    # defusedxml hardens against entity-expansion ("billion laughs"),
    # external-entity (XXE) and DTD-retrieval attacks on untrusted GPX.
    from defusedxml.ElementTree import fromstring as _safe_xml_fromstring

    _XML_HARDENED = True
except ImportError:  # pragma: no cover - falls back if dependency missing
    warnings.warn(
        "defusedxml is not installed; GPX parsing falls back to xml.etree and is less hardened.",
        RuntimeWarning,
        stacklevel=2,
    )
    _safe_xml_fromstring = ET.fromstring  # type: ignore[assignment]
    _XML_HARDENED = False

import numpy as np

from engines.core.metric_contracts import annotate_payload


EARTH_RADIUS_M = 6_371_000.0
G = 9.80665
AIR_DENSITY_KG_M3 = 1.18
DEFAULT_CRR = 0.005
DEFAULT_CDA = 0.32
DEFAULT_DRIVETRAIN_EFFICIENCY = 0.975
DEFAULT_GROSS_EFFICIENCY = 0.22


@dataclass(frozen=True)
class CoursePoint:
    """One geospatial route point."""

    lat: float
    lon: float
    ele_m: float
    distance_m: float = 0.0

    def to_dict(self) -> Dict[str, float]:
        return {
            "lat": round(self.lat, 7),
            "lon": round(self.lon, 7),
            "ele_m": round(self.ele_m, 1),
            "distance_m": round(self.distance_m, 1),
        }


@dataclass(frozen=True)
class CourseSegment:
    """Distance/elevation segment between consecutive course points."""

    start_m: float
    end_m: float
    distance_m: float
    elevation_delta_m: float
    grade_pct: float

    @property
    def terrain(self) -> str:
        if self.grade_pct >= 4.0:
            return "climb"
        if self.grade_pct <= -3.0:
            return "descent"
        return "rolling"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start_m": round(self.start_m, 1),
            "end_m": round(self.end_m, 1),
            "distance_m": round(self.distance_m, 1),
            "elevation_delta_m": round(self.elevation_delta_m, 1),
            "grade_pct": round(self.grade_pct, 2),
            "terrain": self.terrain,
        }


@dataclass(frozen=True)
class Climb:
    """Contiguous uphill course section."""

    start_m: float
    end_m: float
    distance_m: float
    gain_m: float
    avg_grade_pct: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start_km": round(self.start_m / 1000.0, 2),
            "end_km": round(self.end_m / 1000.0, 2),
            "distance_km": round(self.distance_m / 1000.0, 2),
            "gain_m": round(self.gain_m, 0),
            "avg_grade_pct": round(self.avg_grade_pct, 1),
        }


@dataclass(frozen=True)
class AthleteRaceProfile:
    """Rider and equipment inputs used by the race simulator."""

    weight_kg: float
    ftp_w: float
    bike_weight_kg: float = 8.0
    cda: float = DEFAULT_CDA
    crr: float = DEFAULT_CRR
    drivetrain_efficiency: float = DEFAULT_DRIVETRAIN_EFFICIENCY
    gross_efficiency: float = DEFAULT_GROSS_EFFICIENCY
    mlss_w: Optional[float] = None
    fatmax_w: Optional[float] = None
    vo2max: Optional[float] = None
    vlamax: Optional[float] = None

    @classmethod
    def from_metabolic_snapshot(
        cls,
        *,
        weight_kg: float,
        ftp_w: float,
        snapshot: Optional[Dict[str, Any]] = None,
        bike_weight_kg: float = 8.0,
        cda: float = DEFAULT_CDA,
        crr: float = DEFAULT_CRR,
    ) -> "AthleteRaceProfile":
        snapshot = snapshot or {}
        return cls(
            weight_kg=weight_kg,
            ftp_w=ftp_w,
            bike_weight_kg=bike_weight_kg,
            cda=cda,
            crr=crr,
            mlss_w=_maybe_float(snapshot.get("mlss_power_watts")),
            fatmax_w=_maybe_float(snapshot.get("fatmax_power_watts")),
            vo2max=_maybe_float(snapshot.get("estimated_vo2max")),
            vlamax=_maybe_float(snapshot.get("estimated_vlamax_mmol_L_s")),
        )


def _maybe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        out = float(value)
        return out if np.isfinite(out) else None
    except (TypeError, ValueError):
        return None


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2.0 * EARTH_RADIUS_M * atan(sqrt(a) / max(sqrt(1.0 - a), 1e-12))


def _xml_namespace(root: ET.Element) -> str:
    if root.tag.startswith("{"):
        return root.tag.split("}", 1)[0][1:]
    return ""


def parse_gpx_course(gpx_path_or_text: str | Path) -> List[CoursePoint]:
    """
    Parse a GPX file path or raw GPX XML string into cumulative-distance points.
    """
    text: str
    candidate = Path(gpx_path_or_text) if not str(gpx_path_or_text).lstrip().startswith("<") else None
    if candidate is not None and candidate.exists():
        text = candidate.read_text(encoding="utf-8")
    else:
        text = str(gpx_path_or_text)

    # Guard against oversized GPX before handing bytes to the XML parser.
    try:
        from engines.core.security import MAX_GPX_BYTES

        if len(text.encode("utf-8", errors="ignore")) > MAX_GPX_BYTES:
            raise ValueError("GPX course exceeds the maximum allowed size.")
    except ImportError:  # pragma: no cover
        pass

    root = _safe_xml_fromstring(text)
    ns = _xml_namespace(root)
    prefix = f"{{{ns}}}" if ns else ""

    raw_points: List[Tuple[float, float, float]] = []
    for trkpt in root.iter(f"{prefix}trkpt"):
        lat = float(trkpt.attrib["lat"])
        lon = float(trkpt.attrib["lon"])
        ele_node = trkpt.find(f"{prefix}ele")
        ele = float(ele_node.text) if ele_node is not None and ele_node.text else 0.0
        raw_points.append((lat, lon, ele))

    if not raw_points:
        for rtept in root.iter(f"{prefix}rtept"):
            lat = float(rtept.attrib["lat"])
            lon = float(rtept.attrib["lon"])
            ele_node = rtept.find(f"{prefix}ele")
            ele = float(ele_node.text) if ele_node is not None and ele_node.text else 0.0
            raw_points.append((lat, lon, ele))

    if len(raw_points) < 2:
        raise ValueError("GPX course needs at least two track or route points")

    points: List[CoursePoint] = []
    cumulative = 0.0
    prev: Optional[Tuple[float, float, float]] = None
    for lat, lon, ele in raw_points:
        if prev is not None:
            cumulative += _haversine_m(prev[0], prev[1], lat, lon)
        points.append(CoursePoint(lat=lat, lon=lon, ele_m=ele, distance_m=cumulative))
        prev = (lat, lon, ele)
    return points


def build_course_segments(points: Sequence[CoursePoint], min_segment_m: float = 25.0) -> List[CourseSegment]:
    """
    Build grade segments from route points, merging tiny point-to-point gaps.
    """
    if len(points) < 2:
        return []

    raw: List[CourseSegment] = []
    start = points[0]
    prev = points[0]
    accum_dist = 0.0
    accum_ele = 0.0

    for point in points[1:]:
        dist = max(0.0, point.distance_m - prev.distance_m)
        ele = point.ele_m - prev.ele_m
        accum_dist += dist
        accum_ele += ele
        if accum_dist >= min_segment_m:
            grade = (accum_ele / accum_dist) * 100.0 if accum_dist > 0 else 0.0
            raw.append(
                CourseSegment(
                    start_m=start.distance_m,
                    end_m=point.distance_m,
                    distance_m=accum_dist,
                    elevation_delta_m=accum_ele,
                    grade_pct=float(np.clip(grade, -25.0, 25.0)),
                )
            )
            start = point
            accum_dist = 0.0
            accum_ele = 0.0
        prev = point

    if accum_dist > 1.0:
        grade = (accum_ele / accum_dist) * 100.0
        raw.append(
            CourseSegment(
                start_m=start.distance_m,
                end_m=points[-1].distance_m,
                distance_m=accum_dist,
                elevation_delta_m=accum_ele,
                grade_pct=float(np.clip(grade, -25.0, 25.0)),
            )
        )

    return raw


def detect_climbs(
    segments: Sequence[CourseSegment],
    min_gain_m: float = 30.0,
    min_distance_m: float = 300.0,
    min_avg_grade_pct: float = 3.0,
) -> List[Climb]:
    """Detect contiguous meaningful uphill sections."""
    climbs: List[Climb] = []
    current: List[CourseSegment] = []

    def flush() -> None:
        if not current:
            return
        distance = sum(seg.distance_m for seg in current)
        gain = sum(max(0.0, seg.elevation_delta_m) for seg in current)
        avg_grade = gain / distance * 100.0 if distance > 0 else 0.0
        if gain >= min_gain_m and distance >= min_distance_m and avg_grade >= min_avg_grade_pct:
            climbs.append(
                Climb(
                    start_m=current[0].start_m,
                    end_m=current[-1].end_m,
                    distance_m=distance,
                    gain_m=gain,
                    avg_grade_pct=avg_grade,
                )
            )

    for seg in segments:
        if seg.grade_pct >= min_avg_grade_pct or (current and seg.grade_pct >= 1.0):
            current.append(seg)
        else:
            flush()
            current = []
    flush()
    return climbs


def analyze_course(points: Sequence[CoursePoint]) -> Dict[str, Any]:
    """Summarize route distance, elevation and climb profile."""
    segments = build_course_segments(points)
    climbs = detect_climbs(segments)
    total_distance = points[-1].distance_m if points else 0.0
    elevation_gain = sum(max(0.0, seg.elevation_delta_m) for seg in segments)
    elevation_loss = sum(abs(min(0.0, seg.elevation_delta_m)) for seg in segments)
    terrain_m = {
        "climb": sum(seg.distance_m for seg in segments if seg.terrain == "climb"),
        "rolling": sum(seg.distance_m for seg in segments if seg.terrain == "rolling"),
        "descent": sum(seg.distance_m for seg in segments if seg.terrain == "descent"),
    }
    return {
        "status": "success",
        "distance_km": round(total_distance / 1000.0, 2),
        "elevation_gain_m": round(elevation_gain, 0),
        "elevation_loss_m": round(elevation_loss, 0),
        "n_points": len(points),
        "n_segments": len(segments),
        "terrain_distribution": {
            key: round(value / total_distance, 3) if total_distance > 0 else 0.0
            for key, value in terrain_m.items()
        },
        "climbs": [climb.to_dict() for climb in climbs],
        "segments": [seg.to_dict() for seg in segments],
    }


def _target_power(seg: CourseSegment, profile: AthleteRaceProfile) -> float:
    ftp = profile.ftp_w
    mlss = profile.mlss_w or ftp
    if seg.grade_pct >= 8.0:
        target = ftp * 0.95
    elif seg.grade_pct >= 5.0:
        target = ftp * 0.90
    elif seg.grade_pct >= 3.0:
        target = ftp * 0.84
    elif seg.grade_pct <= -6.0:
        target = ftp * 0.25
    elif seg.grade_pct <= -3.0:
        target = ftp * 0.40
    else:
        target = ftp * 0.76
    return float(min(target, mlss * 1.03))


def _speed_for_power(
    power_w: float,
    grade_pct: float,
    profile: AthleteRaceProfile,
    min_speed_mps: float = 1.5,
    max_speed_mps: float = 26.0,
) -> float:
    """Solve steady-state cycling speed for a power target."""
    mass = profile.weight_kg + profile.bike_weight_kg
    grade = grade_pct / 100.0

    def required_power(speed: float) -> float:
        rolling = mass * G * profile.crr * speed
        gravity = mass * G * grade * speed
        aero = 0.5 * AIR_DENSITY_KG_M3 * profile.cda * speed ** 3
        wheel_power = rolling + gravity + aero
        return wheel_power / max(profile.drivetrain_efficiency, 0.5)

    low, high = min_speed_mps, max_speed_mps
    # On steep descents, gravity may already exceed target power. Allow coasting.
    if grade < 0 and required_power(low) > power_w:
        return low

    for _ in range(48):
        mid = (low + high) / 2.0
        if required_power(mid) > power_w:
            high = mid
        else:
            low = mid
    return (low + high) / 2.0


def simulate_race(
    points: Sequence[CoursePoint],
    profile: AthleteRaceProfile,
) -> Dict[str, Any]:
    """Simulate race time, energy cost and pacing strategy for a GPX course."""
    course = analyze_course(points)
    segments = build_course_segments(points)
    if not segments:
        return {"status": "error", "message": "No course segments available"}

    plan: List[Dict[str, Any]] = []
    total_time_s = 0.0
    total_work_kj = 0.0
    weighted_power_time = 0.0
    climb_time_s = 0.0
    descent_time_s = 0.0

    for seg in segments:
        power = _target_power(seg, profile)
        speed = _speed_for_power(power, seg.grade_pct, profile)
        time_s = seg.distance_m / max(speed, 0.1)
        work_kj = power * time_s / 1000.0
        total_time_s += time_s
        total_work_kj += work_kj
        weighted_power_time += power * time_s
        if seg.terrain == "climb":
            climb_time_s += time_s
        elif seg.terrain == "descent":
            descent_time_s += time_s
        plan.append({
            "start_km": round(seg.start_m / 1000.0, 2),
            "end_km": round(seg.end_m / 1000.0, 2),
            "distance_km": round(seg.distance_m / 1000.0, 3),
            "grade_pct": round(seg.grade_pct, 1),
            "terrain": seg.terrain,
            "target_power_w": round(power, 0),
            "target_if": round(power / profile.ftp_w, 2),
            "estimated_speed_kmh": round(speed * 3.6, 1),
            "estimated_time_min": round(time_s / 60.0, 1),
            "mechanical_work_kj": round(work_kj, 1),
        })

    avg_power = weighted_power_time / total_time_s if total_time_s > 0 else 0.0
    metabolic_kj = total_work_kj / max(profile.gross_efficiency, 0.05)
    metabolic_kcal = metabolic_kj / 4.184
    carbs_g = max(0.0, metabolic_kcal * 0.58 / 4.0)
    bottles_500ml = max(1.0, total_time_s / 3600.0 * 1.1)

    strategy = _strategy_notes(course, profile, total_time_s, carbs_g, bottles_500ml)
    result = {
        "status": "success",
        "course": {k: v for k, v in course.items() if k != "segments"},
        "prediction": {
            "estimated_time_s": round(total_time_s, 0),
            "estimated_time_h": round(total_time_s / 3600.0, 2),
            "avg_speed_kmh": round((course["distance_km"] / (total_time_s / 3600.0)), 1)
            if total_time_s > 0 else None,
            "avg_power_w": round(avg_power, 0),
            "avg_if": round(avg_power / profile.ftp_w, 2),
            "mechanical_work_kj": round(total_work_kj, 0),
            "metabolic_cost_kcal": round(metabolic_kcal, 0),
            "estimated_carbohydrate_g": round(carbs_g, 0),
            "estimated_fluid_500ml_bottles": round(bottles_500ml, 1),
            "climb_time_min": round(climb_time_s / 60.0, 1),
            "descent_time_min": round(descent_time_s / 60.0, 1),
        },
        "strategy": strategy,
        "pacing_plan": plan,
    }
    return annotate_payload(
        result,
        module_name="race_prediction_engine",
        method="gpx_physics_pacing_model",
        confidence=0.68,
        limitations=[
            "No wind/drafting/surface model.",
            "Course points and elevation quality strongly affect predictions.",
        ],
    )


def _strategy_notes(
    course: Dict[str, Any],
    profile: AthleteRaceProfile,
    total_time_s: float,
    carbs_g: float,
    bottles_500ml: float,
) -> Dict[str, Any]:
    climbs = course.get("climbs", [])
    longest = max(climbs, key=lambda c: c["distance_km"], default=None)
    notes = [
        "Keep climbs controlled; avoid repeated spikes above threshold early.",
        "Use descents for fueling and recovery rather than chasing power targets.",
        "Treat the first third of the course as controlled even if speed feels easy.",
    ]
    if longest:
        notes.append(
            f"Key climb: {longest['distance_km']} km at {longest['avg_grade_pct']}% "
            f"from km {longest['start_km']} to {longest['end_km']}."
        )
    if profile.fatmax_w:
        notes.append(f"Use {round(profile.fatmax_w)} W as the efficient endurance anchor on long steady sections.")

    return {
        "power_caps": {
            "rolling_if": 0.76,
            "moderate_climb_if": 0.84,
            "steep_climb_if": 0.95,
            "descent_if": 0.25,
        },
        "fueling": {
            "duration_h": round(total_time_s / 3600.0, 2),
            "carbohydrate_target_g": round(carbs_g, 0),
            "carbohydrate_g_per_h": round(carbs_g / max(total_time_s / 3600.0, 0.1), 0),
            "fluid_500ml_bottles": round(bottles_500ml, 1),
        },
        "coach_notes": notes,
    }


def simulate_gpx_race(
    gpx_path_or_text: str | Path,
    *,
    weight_kg: float,
    ftp_w: float,
    metabolic_snapshot: Optional[Dict[str, Any]] = None,
    bike_weight_kg: float = 8.0,
    cda: float = DEFAULT_CDA,
    crr: float = DEFAULT_CRR,
) -> Dict[str, Any]:
    """Convenience API: parse GPX and simulate a race in one call."""
    points = parse_gpx_course(gpx_path_or_text)
    profile = AthleteRaceProfile.from_metabolic_snapshot(
        weight_kg=weight_kg,
        ftp_w=ftp_w,
        snapshot=metabolic_snapshot,
        bike_weight_kg=bike_weight_kg,
        cda=cda,
        crr=crr,
    )
    return simulate_race(points, profile)
