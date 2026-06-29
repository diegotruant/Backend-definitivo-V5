"""Workout domain models and normalization helpers.

These models are intentionally lightweight and dependency-free.  The API layer can
validate JSON with Pydantic, but the engines work on plain dataclasses so they can
be used from scripts, tests, background jobs, or future DB service layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


class WorkoutValidationError(ValueError):
    """Raised when a workout structure is not machine-readable."""


@dataclass
class WorkoutStep:
    step_id: str
    type: str
    duration_s: int
    target_type: str = "free"
    target_w: Optional[float] = None
    target_min_w: Optional[float] = None
    target_max_w: Optional[float] = None
    target_pct_cp: Optional[float] = None
    target_min_pct_cp: Optional[float] = None
    target_max_pct_cp: Optional[float] = None
    target_pct_ftp: Optional[float] = None
    target_min_pct_ftp: Optional[float] = None
    target_max_pct_ftp: Optional[float] = None
    target_hr: Optional[float] = None
    target_min_hr: Optional[float] = None
    target_max_hr: Optional[float] = None
    cadence_min_rpm: Optional[float] = None
    cadence_max_rpm: Optional[float] = None
    is_key_step: bool = False
    notes: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    def power_range(self, athlete_profile: Optional[Dict[str, Any]] = None) -> Optional[Tuple[float, float]]:
        """Return a concrete target power range in Watts when possible."""
        profile = athlete_profile or {}
        cp = _num(profile.get("cp_w") or profile.get("critical_power_w"))
        ftp = _num(profile.get("ftp_w") or profile.get("ftp"))

        if self.target_min_w is not None or self.target_max_w is not None:
            lo = self.target_min_w if self.target_min_w is not None else self.target_max_w
            hi = self.target_max_w if self.target_max_w is not None else self.target_min_w
            if lo is None or hi is None:
                return None
            return float(min(lo, hi)), float(max(lo, hi))
        if self.target_w is not None:
            return float(self.target_w), float(self.target_w)

        if cp:
            if self.target_min_pct_cp is not None or self.target_max_pct_cp is not None:
                lo_pct = self.target_min_pct_cp if self.target_min_pct_cp is not None else self.target_max_pct_cp
                hi_pct = self.target_max_pct_cp if self.target_max_pct_cp is not None else self.target_min_pct_cp
                if lo_pct is not None and hi_pct is not None:
                    return cp * min(lo_pct, hi_pct) / 100.0, cp * max(lo_pct, hi_pct) / 100.0
            if self.target_pct_cp is not None:
                return cp * self.target_pct_cp / 100.0, cp * self.target_pct_cp / 100.0

        if ftp:
            if self.target_min_pct_ftp is not None or self.target_max_pct_ftp is not None:
                lo_pct = self.target_min_pct_ftp if self.target_min_pct_ftp is not None else self.target_max_pct_ftp
                hi_pct = self.target_max_pct_ftp if self.target_max_pct_ftp is not None else self.target_min_pct_ftp
                if lo_pct is not None and hi_pct is not None:
                    return ftp * min(lo_pct, hi_pct) / 100.0, ftp * max(lo_pct, hi_pct) / 100.0
            if self.target_pct_ftp is not None:
                return ftp * self.target_pct_ftp / 100.0, ftp * self.target_pct_ftp / 100.0

        return None

    def hr_range(self) -> Optional[Tuple[float, float]]:
        if self.target_min_hr is not None or self.target_max_hr is not None:
            lo = self.target_min_hr if self.target_min_hr is not None else self.target_max_hr
            hi = self.target_max_hr if self.target_max_hr is not None else self.target_min_hr
            if lo is None or hi is None:
                return None
            return float(min(lo, hi)), float(max(lo, hi))
        if self.target_hr is not None:
            return float(self.target_hr), float(self.target_hr)
        return None

    def resolved_target_power_w(self, athlete_profile: Optional[Dict[str, Any]] = None) -> Optional[float]:
        rng = self.power_range(athlete_profile)
        if not rng:
            return None
        return (rng[0] + rng[1]) / 2.0

    def to_dict(self, athlete_profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        out = dict(self.raw)
        out.update({
            "step_id": self.step_id,
            "type": self.type,
            "duration_s": self.duration_s,
            "target_type": self.target_type,
            "is_key_step": self.is_key_step,
        })
        power_range = self.power_range(athlete_profile)
        if power_range:
            out["resolved_target_min_w"] = round(power_range[0], 1)
            out["resolved_target_max_w"] = round(power_range[1], 1)
            out["resolved_target_w"] = round((power_range[0] + power_range[1]) / 2.0, 1)
        hr_range = self.hr_range()
        if hr_range:
            out["resolved_target_min_hr"] = round(hr_range[0], 1)
            out["resolved_target_max_hr"] = round(hr_range[1], 1)
        return out


@dataclass
class WorkoutDefinition:
    title: str
    steps: List[WorkoutStep]
    workout_id: Optional[str] = None
    description: Optional[str] = None
    discipline: str = "cycling"
    goal: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration_s(self) -> int:
        return int(sum(step.duration_s for step in self.steps))

    def to_dict(self, athlete_profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "workout_id": self.workout_id,
            "title": self.title,
            "description": self.description,
            "discipline": self.discipline,
            "goal": self.goal,
            "tags": self.tags,
            "estimated_duration_s": self.duration_s,
            "steps": [s.to_dict(athlete_profile) for s in self.steps],
        }


def _num(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _step_declares_power_target(step: WorkoutStep) -> bool:
    return any(
        getattr(step, field) is not None
        for field in (
            "target_w",
            "target_min_w",
            "target_max_w",
            "target_pct_cp",
            "target_min_pct_cp",
            "target_max_pct_cp",
            "target_pct_ftp",
            "target_min_pct_ftp",
            "target_max_pct_ftp",
        )
    )


def _step_declares_hr_target(step: WorkoutStep) -> bool:
    return any(getattr(step, field) is not None for field in ("target_hr", "target_min_hr", "target_max_hr"))


def _step_declares_measurable_target(step: WorkoutStep) -> bool:
    if _step_declares_power_target(step) or _step_declares_hr_target(step):
        return True
    return step.cadence_min_rpm is not None and step.cadence_max_rpm is not None


def _step_is_key(step: WorkoutStep) -> bool:
    return step.is_key_step or step.type.lower() in {"work", "interval"}


def normalize_workout(payload: Dict[str, Any]) -> WorkoutDefinition:
    """Convert a JSON-like workout payload into a validated WorkoutDefinition.

    Accepted inputs use either `steps` or `structure`.  This keeps the endpoint
    compatible with coach-created templates, frontend drafts, and DB rows.
    """
    if not isinstance(payload, dict):
        raise WorkoutValidationError("workout must be a JSON object")

    steps_raw = payload.get("steps") or payload.get("structure")
    if not isinstance(steps_raw, list) or not steps_raw:
        raise WorkoutValidationError("workout.steps must be a non-empty array")

    steps: List[WorkoutStep] = []
    for idx, raw in enumerate(steps_raw):
        if not isinstance(raw, dict):
            raise WorkoutValidationError(f"step {idx + 1} must be a JSON object")
        duration = _num(raw.get("duration_s") or raw.get("duration") or raw.get("seconds"))
        if duration is None or duration <= 0:
            raise WorkoutValidationError(f"step {idx + 1} has invalid duration_s")
        step_id = str(raw.get("step_id") or raw.get("id") or f"step_{idx + 1}")
        step_type = str(raw.get("type") or raw.get("step_type") or "work")
        target_type = str(raw.get("target_type") or raw.get("target") or "free")
        steps.append(WorkoutStep(
            step_id=step_id,
            type=step_type,
            duration_s=int(round(duration)),
            target_type=target_type,
            target_w=_num(raw.get("target_w") or raw.get("target_power_w")),
            target_min_w=_num(raw.get("target_min_w") or raw.get("target_min_power_w")),
            target_max_w=_num(raw.get("target_max_w") or raw.get("target_max_power_w")),
            target_pct_cp=_num(raw.get("target_pct_cp") or raw.get("target_power_pct_cp")),
            target_min_pct_cp=_num(raw.get("target_min_pct_cp")),
            target_max_pct_cp=_num(raw.get("target_max_pct_cp")),
            target_pct_ftp=_num(raw.get("target_pct_ftp") or raw.get("target_power_pct_ftp")),
            target_min_pct_ftp=_num(raw.get("target_min_pct_ftp")),
            target_max_pct_ftp=_num(raw.get("target_max_pct_ftp")),
            target_hr=_num(raw.get("target_hr") or raw.get("target_bpm")),
            target_min_hr=_num(raw.get("target_min_hr") or raw.get("target_min_bpm")),
            target_max_hr=_num(raw.get("target_max_hr") or raw.get("target_max_bpm")),
            cadence_min_rpm=_num(raw.get("cadence_min_rpm") or raw.get("target_min_cadence")),
            cadence_max_rpm=_num(raw.get("cadence_max_rpm") or raw.get("target_max_cadence")),
            is_key_step=_bool(raw.get("is_key_step") or raw.get("key"), default=False),
            notes=raw.get("notes"),
            raw=dict(raw),
        ))

    return WorkoutDefinition(
        workout_id=payload.get("workout_id") or payload.get("id"),
        title=str(payload.get("title") or payload.get("name") or "Untitled workout"),
        description=payload.get("description"),
        discipline=str(payload.get("discipline") or "cycling"),
        goal=payload.get("goal"),
        tags=list(payload.get("tags") or []),
        steps=steps,
        raw=dict(payload),
    )


def validate_workout_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    workout = normalize_workout(payload)
    warnings: List[str] = []
    key_steps = [s for s in workout.steps if _step_is_key(s)]
    if not key_steps:
        warnings.append("No key/work intervals detected; compliance will be duration-focused.")
    for step in key_steps:
        if not _step_declares_measurable_target(step):
            warnings.append(
                f"Step {step.step_id} has no measurable target (power/HR/cadence); compliance will be duration-only."
            )
    step_ids = [s.step_id for s in workout.steps]
    if len(step_ids) != len(set(step_ids)):
        warnings.append("Duplicate step_id values detected; compliance alignment may be ambiguous.")
    if workout.duration_s < 300:
        warnings.append("Workout duration is very short (<5 min).")
    return {
        "status": "valid",
        "workout": workout.to_dict(),
        "summary": {
            "n_steps": len(workout.steps),
            "duration_s": workout.duration_s,
            "key_steps": len(key_steps),
        },
        "warnings": warnings,
    }


def materialize_workout(payload: Dict[str, Any], athlete_profile: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve percentage/zone-style targets into athlete-specific watts when possible."""
    workout = normalize_workout(payload)
    out = workout.to_dict(athlete_profile)
    unresolved: List[str] = []
    prescription_warnings: List[str] = []
    for model_step, step in zip(workout.steps, out["steps"]):
        declares_measurable = _step_declares_measurable_target(model_step)
        typed_target = model_step.target_type.lower() not in {"free", "open", "rest"}
        if not declares_measurable and not typed_target:
            continue
        power_ok = not _step_declares_power_target(model_step) or "resolved_target_w" in step
        hr_ok = not _step_declares_hr_target(model_step) or "resolved_target_min_hr" in step
        if typed_target and not declares_measurable:
            unresolved.append(step["step_id"])
        elif not (power_ok and hr_ok):
            unresolved.append(step["step_id"])
    if unresolved:
        prescription_warnings.append(
            "Some steps could not be resolved to concrete watts/HR; provide CP/FTP (and HR zones when needed) in athlete profile."
        )
    out["prescription_status"] = "resolved" if not unresolved else "partially_resolved"
    out["unresolved_steps"] = unresolved
    out["prescription_warnings"] = prescription_warnings
    return out
