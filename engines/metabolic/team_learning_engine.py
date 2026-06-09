"""
Team Learning Engine
====================

A storage-agnostic calibration layer for physiology-informed learning.

This module closes the practical loop that a World Tour team needs:

    model prediction BEFORE a validated test
        -> validated Mader / lactate / lab measurement
        -> observed prediction error
        -> athlete / phenotype / team calibration bias
        -> next estimate with correction + audit trail

Important design choice
-----------------------
The engine does NOT replace the Mader/metabolic model. It learns a bounded
residual correction on top of the physiology model. This protects the system
from overfitting small cohorts, noisy tests, or protocol differences.

The API layer can persist ``TeamCalibrationModel.to_dict()`` in any database
and send it back on the next request. The engine itself remains stateless.

Tier: MODEL — empirical calibration layer, auditable and bounded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from math import sqrt
from statistics import mean, pstdev
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


SUPPORTED_PARAMETERS = {"mlss", "vo2max", "vlamax", "fatmax", "map"}

# Parameter-specific caps. These are intentionally conservative: the learned
# layer should correct model bias, not overpower physiology.
DEFAULT_ABS_CAPS = {
    "mlss": 25.0,      # W
    "fatmax": 25.0,    # W
    "map": 35.0,       # W
    "vo2max": 4.0,     # ml/kg/min
    "vlamax": 0.08,    # mmol/L/s
}
DEFAULT_PCT_CAPS = {
    "mlss": 0.05,
    "fatmax": 0.07,
    "map": 0.05,
    "vo2max": 0.05,
    "vlamax": 0.15,
}


def _norm_parameter(parameter: str) -> str:
    p = str(parameter or "").strip().lower()
    aliases = {
        "mlss_power": "mlss",
        "mlss_watts": "mlss",
        "lt2": "mlss",
        "lt2_power": "mlss",
        "vo2": "vo2max",
        "vo2_max": "vo2max",
        "vla": "vlamax",
        "vla_max": "vlamax",
        "fat_max": "fatmax",
        "fatmax_power": "fatmax",
        "map_w": "map",
    }
    p = aliases.get(p, p)
    if p not in SUPPORTED_PARAMETERS:
        raise ValueError(f"Unsupported calibration parameter: {parameter!r}")
    return p


def _as_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    if value is None:
        return date.today()
    return date.fromisoformat(str(value))


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class ValidationEvent:
    """
    One audited comparison between a pre-test prediction and a validated value.

    ``predicted_value`` MUST be the value the model produced before seeing the
    test result. This is what makes learning honest and scientifically auditable.
    Error convention: measured - predicted. A negative MLSS error means the
    model overestimated MLSS.
    """

    athlete_id: str
    team_id: str
    parameter: str
    predicted_value: float
    measured_value: float
    test_date: date = field(default_factory=date.today)
    model_version: str = "unknown"
    protocol: str = "unknown"
    phenotype: Optional[str] = None
    data_depth_score: float = 1.0          # 0..1 quality of the pre-test data
    measurement_confidence: float = 1.0    # 0..1 quality of the validating test
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameter", _norm_parameter(self.parameter))
        object.__setattr__(self, "test_date", _as_date(self.test_date))
        object.__setattr__(self, "predicted_value", float(self.predicted_value))
        object.__setattr__(self, "measured_value", float(self.measured_value))
        object.__setattr__(self, "data_depth_score", _clamp(float(self.data_depth_score), 0.0, 1.0))
        object.__setattr__(self, "measurement_confidence", _clamp(float(self.measurement_confidence), 0.0, 1.0))
        if not self.athlete_id:
            raise ValueError("athlete_id is required")
        if not self.team_id:
            raise ValueError("team_id is required")
        if self.predicted_value <= 0:
            raise ValueError("predicted_value must be positive")

    @property
    def error_abs(self) -> float:
        return self.measured_value - self.predicted_value

    @property
    def error_pct(self) -> float:
        return self.error_abs / self.predicted_value

    @property
    def weight(self) -> float:
        # We trust high-quality lab/test observations more than low-quality
        # field validations, while still letting partial data contribute.
        return max(0.05, self.data_depth_score * self.measurement_confidence)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "athlete_id": self.athlete_id,
            "team_id": self.team_id,
            "parameter": self.parameter,
            "predicted_value": self.predicted_value,
            "measured_value": self.measured_value,
            "error_abs": self.error_abs,
            "error_pct": self.error_pct,
            "test_date": self.test_date.isoformat(),
            "model_version": self.model_version,
            "protocol": self.protocol,
            "phenotype": self.phenotype,
            "data_depth_score": self.data_depth_score,
            "measurement_confidence": self.measurement_confidence,
            "weight": self.weight,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ValidationEvent":
        return cls(
            athlete_id=str(d.get("athlete_id") or ""),
            team_id=str(d.get("team_id") or ""),
            parameter=str(d.get("parameter") or ""),
            predicted_value=float(d.get("predicted_value")),
            measured_value=float(d.get("measured_value")),
            test_date=_as_date(d.get("test_date")),
            model_version=str(d.get("model_version") or "unknown"),
            protocol=str(d.get("protocol") or "unknown"),
            phenotype=d.get("phenotype"),
            data_depth_score=float(d.get("data_depth_score", 1.0)),
            measurement_confidence=float(d.get("measurement_confidence", 1.0)),
            notes=str(d.get("notes") or ""),
        )


@dataclass
class CalibrationStats:
    """Error statistics for one slice: team, phenotype, or athlete."""

    parameter: str
    scope: str
    key: str
    n: int
    weighted_bias: float
    mae: float
    rmse: float
    std: float
    mean_error_pct: float
    latest_test_date: Optional[date] = None

    @property
    def ci95_half_width(self) -> Optional[float]:
        if self.n < 2:
            return None
        return 1.96 * self.std / sqrt(self.n)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "parameter": self.parameter,
            "scope": self.scope,
            "key": self.key,
            "n": self.n,
            "weighted_bias": round(self.weighted_bias, 4),
            "mae": round(self.mae, 4),
            "rmse": round(self.rmse, 4),
            "std": round(self.std, 4),
            "mean_error_pct": round(self.mean_error_pct, 5),
            "ci95_half_width": None if self.ci95_half_width is None else round(self.ci95_half_width, 4),
            "latest_test_date": self.latest_test_date.isoformat() if self.latest_test_date else None,
        }


@dataclass
class CorrectionConfig:
    """Safety settings for learned residual corrections."""

    min_team_events: int = 5
    min_phenotype_events: int = 4
    min_athlete_events: int = 2
    max_abs_correction: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_ABS_CAPS))
    max_pct_correction: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_PCT_CAPS))

    def cap_for(self, parameter: str, predicted_value: float) -> float:
        p = _norm_parameter(parameter)
        abs_cap = float(self.max_abs_correction.get(p, DEFAULT_ABS_CAPS[p]))
        pct_cap = float(self.max_pct_correction.get(p, DEFAULT_PCT_CAPS[p])) * abs(float(predicted_value))
        return min(abs_cap, pct_cap)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "min_team_events": self.min_team_events,
            "min_phenotype_events": self.min_phenotype_events,
            "min_athlete_events": self.min_athlete_events,
            "max_abs_correction": self.max_abs_correction,
            "max_pct_correction": self.max_pct_correction,
        }

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "CorrectionConfig":
        if not d:
            return cls()
        return cls(
            min_team_events=int(d.get("min_team_events", 5)),
            min_phenotype_events=int(d.get("min_phenotype_events", 4)),
            min_athlete_events=int(d.get("min_athlete_events", 2)),
            max_abs_correction=dict(d.get("max_abs_correction") or DEFAULT_ABS_CAPS),
            max_pct_correction=dict(d.get("max_pct_correction") or DEFAULT_PCT_CAPS),
        )


def _weighted_mean(values: Sequence[Tuple[float, float]]) -> float:
    denom = sum(w for _, w in values)
    if denom <= 0:
        return mean(v for v, _ in values)
    return sum(v * w for v, w in values) / denom


def _stats(events: Sequence[ValidationEvent], scope: str, key: str, parameter: str) -> Optional[CalibrationStats]:
    if not events:
        return None
    errors = [e.error_abs for e in events]
    weighted_bias = _weighted_mean([(e.error_abs, e.weight) for e in events])
    mae = mean(abs(e) for e in errors)
    rmse = sqrt(mean(e * e for e in errors))
    std = pstdev(errors) if len(errors) > 1 else 0.0
    mean_error_pct = _weighted_mean([(e.error_pct, e.weight) for e in events])
    latest = max(e.test_date for e in events)
    return CalibrationStats(
        parameter=parameter,
        scope=scope,
        key=key,
        n=len(events),
        weighted_bias=weighted_bias,
        mae=mae,
        rmse=rmse,
        std=std,
        mean_error_pct=mean_error_pct,
        latest_test_date=latest,
    )


@dataclass
class TeamCalibrationModel:
    """
    Serializable team-level calibration model.

    Events are persisted in the model for auditability. For large production
    datasets this can be replaced by persisted aggregate tables, but keeping
    events here is ideal for the current stateless API contract.
    """

    team_id: str
    events: List[ValidationEvent] = field(default_factory=list)
    config: CorrectionConfig = field(default_factory=CorrectionConfig)
    model_version: str = "team-calibration-v1"

    def add_event(self, event: ValidationEvent) -> None:
        if event.team_id != self.team_id:
            raise ValueError(f"Event team_id {event.team_id!r} does not match model team_id {self.team_id!r}")
        self.events.append(event)

    def add_events(self, events: Iterable[ValidationEvent]) -> None:
        for event in events:
            self.add_event(event)

    @classmethod
    def fit(
        cls,
        events: Iterable[ValidationEvent],
        *,
        team_id: Optional[str] = None,
        config: Optional[CorrectionConfig] = None,
    ) -> "TeamCalibrationModel":
        events_list = list(events)
        if not events_list and not team_id:
            raise ValueError("team_id is required when fitting an empty model")
        tid = team_id or events_list[0].team_id
        model = cls(team_id=tid, config=config or CorrectionConfig())
        model.add_events(events_list)
        return model

    def _events_for(
        self,
        parameter: str,
        *,
        athlete_id: Optional[str] = None,
        phenotype: Optional[str] = None,
    ) -> List[ValidationEvent]:
        p = _norm_parameter(parameter)
        out = [e for e in self.events if e.parameter == p]
        if athlete_id is not None:
            out = [e for e in out if e.athlete_id == athlete_id]
        if phenotype is not None:
            ph = str(phenotype).lower()
            out = [e for e in out if (e.phenotype or "").lower() == ph]
        return out

    def stats(
        self,
        parameter: str,
        *,
        athlete_id: Optional[str] = None,
        phenotype: Optional[str] = None,
    ) -> Dict[str, Any]:
        p = _norm_parameter(parameter)
        result: Dict[str, Any] = {}
        team_stats = _stats(self._events_for(p), "team", self.team_id, p)
        if team_stats:
            result["team"] = team_stats.to_dict()
        if phenotype:
            ph_stats = _stats(self._events_for(p, phenotype=phenotype), "phenotype", phenotype, p)
            if ph_stats:
                result["phenotype"] = ph_stats.to_dict()
        if athlete_id:
            at_stats = _stats(self._events_for(p, athlete_id=athlete_id), "athlete", athlete_id, p)
            if at_stats:
                result["athlete"] = at_stats.to_dict()
        return result

    def correction_for(
        self,
        parameter: str,
        predicted_value: float,
        *,
        athlete_id: Optional[str] = None,
        phenotype: Optional[str] = None,
        data_depth_score: float = 1.0,
    ) -> Dict[str, Any]:
        """
        Return the bounded learned correction and an audit payload.

        The correction is a shrinked blend: athlete bias dominates when enough
        individual validations exist; otherwise phenotype and team priors carry
        modest weight. Low data depth reduces the applied correction.
        """
        p = _norm_parameter(parameter)
        predicted = float(predicted_value)
        data_depth = _clamp(float(data_depth_score), 0.0, 1.0)
        cap = self.config.cap_for(p, predicted)

        slices: List[Tuple[str, CalibrationStats, float, int]] = []
        team_stats = _stats(self._events_for(p), "team", self.team_id, p)
        if team_stats and team_stats.n >= self.config.min_team_events:
            slices.append(("team", team_stats, 0.20, self.config.min_team_events))
        if phenotype:
            ph_stats = _stats(self._events_for(p, phenotype=phenotype), "phenotype", phenotype, p)
            if ph_stats and ph_stats.n >= self.config.min_phenotype_events:
                slices.append(("phenotype", ph_stats, 0.30, self.config.min_phenotype_events))
        if athlete_id:
            at_stats = _stats(self._events_for(p, athlete_id=athlete_id), "athlete", athlete_id, p)
            if at_stats and at_stats.n >= self.config.min_athlete_events:
                slices.append(("athlete", at_stats, 0.50, self.config.min_athlete_events))

        if not slices:
            return {
                "parameter": p,
                "predicted_value": predicted,
                "correction": 0.0,
                "corrected_value": predicted,
                "applied": False,
                "reason": "insufficient_validation_events",
                "cap": cap,
                "data_depth_score": data_depth,
                "components": [],
                "stats": self.stats(p, athlete_id=athlete_id, phenotype=phenotype),
                "tier": "MODEL",
            }

        components = []
        weighted_sum = 0.0
        total_weight = 0.0
        for scope, st, base_weight, min_events in slices:
            # Evidence ramps up gradually above the minimum threshold.
            evidence = _clamp(st.n / max(min_events * 3.0, 1.0), 0.0, 1.0)
            weight = base_weight * (0.35 + 0.65 * evidence)
            raw = st.weighted_bias
            weighted_sum += raw * weight
            total_weight += weight
            components.append({
                "scope": scope,
                "n": st.n,
                "raw_bias": round(raw, 4),
                "blend_weight": round(weight, 4),
                "mae": round(st.mae, 4),
            })

        raw_correction = weighted_sum / total_weight if total_weight > 0 else 0.0
        # Do not fully trust learned corrections when the current estimate was
        # produced from shallow data. The engine should be cautious, not bold.
        quality_shrink = 0.50 + 0.50 * data_depth
        bounded = _clamp(raw_correction * quality_shrink, -cap, cap)
        corrected = max(0.0, predicted + bounded)

        # A simple confidence score for the calibration layer itself.
        n_eff = sum(c["n"] for c in components)
        confidence = _clamp(0.25 + 0.08 * n_eff + 0.25 * data_depth, 0.0, 0.95)

        return {
            "parameter": p,
            "predicted_value": predicted,
            "correction": round(bounded, 4),
            "corrected_value": round(corrected, 4),
            "applied": abs(bounded) > 1e-9,
            "reason": "bounded_residual_calibration",
            "cap": round(cap, 4),
            "raw_correction_before_caps": round(raw_correction, 4),
            "data_depth_score": data_depth,
            "calibration_confidence": round(confidence, 3),
            "components": components,
            "stats": self.stats(p, athlete_id=athlete_id, phenotype=phenotype),
            "tier": "MODEL",
        }

    def calibrate_snapshot(
        self,
        snapshot: Dict[str, Any],
        *,
        athlete_id: Optional[str] = None,
        phenotype: Optional[str] = None,
        data_depth_score: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Apply available corrections to a metabolic snapshot dict."""
        out = dict(snapshot)
        depth = data_depth_score
        if depth is None:
            depth = _safe_float(snapshot.get("data_depth_score"), None)
        if depth is None:
            depth = _safe_float(snapshot.get("confidence"), 1.0)
        depth = 1.0 if depth is None else depth

        mapping = {
            "mlss": ["mlss_power_watts", "mlss_watts", "mlss_power_w"],
            "vo2max": ["estimated_vo2max", "vo2max"],
            "vlamax": ["estimated_vlamax_mmol_L_s", "vlamax", "vlamax_mmol_L_s"],
            "fatmax": ["fatmax_power_watts", "fatmax_watts", "fatmax_power_w"],
            "map": ["map_watts", "map_w"],
        }
        audit: Dict[str, Any] = {}
        for parameter, keys in mapping.items():
            key = next((k for k in keys if _safe_float(out.get(k), None) is not None), None)
            if not key:
                continue
            res = self.correction_for(
                parameter,
                float(out[key]),
                athlete_id=athlete_id,
                phenotype=phenotype or out.get("phenotype"),
                data_depth_score=float(depth),
            )
            if res["applied"]:
                out[f"raw_{key}"] = out[key]
                out[key] = res["corrected_value"]
            audit[parameter] = res
        out["team_calibration"] = {
            "team_id": self.team_id,
            "model_version": self.model_version,
            "athlete_id": athlete_id,
            "phenotype": phenotype or out.get("phenotype"),
            "audit": audit,
        }
        return out

    def accuracy_report(self) -> Dict[str, Any]:
        """Compact dashboard payload for performance scientists."""
        report: Dict[str, Any] = {
            "team_id": self.team_id,
            "model_version": self.model_version,
            "n_events": len(self.events),
            "parameters": {},
            "tier": "MODEL",
        }
        for p in sorted(SUPPORTED_PARAMETERS):
            st = _stats(self._events_for(p), "team", self.team_id, p)
            if st:
                status = "green" if st.n >= self.config.min_team_events and st.mae <= max(1.0, self.config.max_abs_correction[p] * 0.6) else "yellow"
                if st.n < self.config.min_team_events:
                    status = "red"
                d = st.to_dict()
                d["status"] = status
                report["parameters"][p] = d
        return report

    def to_dict(self) -> Dict[str, Any]:
        return {
            "team_id": self.team_id,
            "model_version": self.model_version,
            "config": self.config.to_dict(),
            "events": [e.to_dict() for e in self.events],
            "accuracy_report": self.accuracy_report(),
            "tier": "MODEL",
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TeamCalibrationModel":
        team_id = str(d.get("team_id") or "")
        if not team_id:
            raise ValueError("team_id is required")
        config = CorrectionConfig.from_dict(d.get("config"))
        events = [ValidationEvent.from_dict(e) for e in d.get("events", [])]
        return cls(
            team_id=team_id,
            events=events,
            config=config,
            model_version=str(d.get("model_version") or "team-calibration-v1"),
        )


def validation_events_from_prediction_and_lab(
    *,
    athlete_id: str,
    team_id: str,
    predicted_snapshot: Dict[str, Any],
    measured: Dict[str, Any],
    test_date: Any,
    model_version: str = "unknown",
    protocol: str = "unknown",
    phenotype: Optional[str] = None,
    data_depth_score: float = 1.0,
    measurement_confidence: float = 1.0,
) -> List[ValidationEvent]:
    """
    Convenience helper to create events from a snapshot and a lab/test dict.

    Expected measured keys may be: measured_mlss / mlss_power_w, measured_vo2max /
    vo2max_ml_kg_min, measured_vlamax / vlamax_mmol_L_s, measured_fatmax, map_w.
    """
    predicted_keys = {
        "mlss": ["mlss_power_watts", "mlss_watts", "mlss_power_w"],
        "vo2max": ["estimated_vo2max", "vo2max"],
        "vlamax": ["estimated_vlamax_mmol_L_s", "vlamax", "vlamax_mmol_L_s"],
        "fatmax": ["fatmax_power_watts", "fatmax_watts", "fatmax_power_w"],
        "map": ["map_watts", "map_w"],
    }
    measured_keys = {
        "mlss": ["measured_mlss", "mlss_power_w", "mlss_power_watts", "lt2_power_w"],
        "vo2max": ["measured_vo2max", "vo2max_ml_kg_min", "vo2max"],
        "vlamax": ["measured_vlamax", "vlamax_mmol_L_s", "vlamax"],
        "fatmax": ["measured_fatmax", "fatmax_power_w", "fatmax_power_watts"],
        "map": ["measured_map", "map_w", "map_watts"],
    }
    events: List[ValidationEvent] = []
    for parameter in sorted(SUPPORTED_PARAMETERS):
        pred_key = next((k for k in predicted_keys[parameter] if _safe_float(predicted_snapshot.get(k), None) is not None), None)
        meas_key = next((k for k in measured_keys[parameter] if _safe_float(measured.get(k), None) is not None), None)
        if not pred_key or not meas_key:
            continue
        events.append(ValidationEvent(
            athlete_id=athlete_id,
            team_id=team_id,
            parameter=parameter,
            predicted_value=float(predicted_snapshot[pred_key]),
            measured_value=float(measured[meas_key]),
            test_date=_as_date(test_date),
            model_version=model_version,
            protocol=protocol,
            phenotype=phenotype,
            data_depth_score=data_depth_score,
            measurement_confidence=measurement_confidence,
        ))
    return events
