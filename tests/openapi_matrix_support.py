"""OpenAPI-driven HTTP matrix helpers — minimal payloads and request builders."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
OPENAPI_JSON = ROOT / "openapi" / "openapi.json"
FIT_ASSET = ROOT / "tests" / "assets" / "fit" / "minimal_power_hr_lap_hrv.fit"

ATHLETE: Dict[str, Any] = {
    "weight_kg": 70,
    "gender": "MALE",
    "training_years": 10,
    "discipline": "ENDURANCE",
}
MMP: Dict[str, float] = {"5": 900, "60": 400, "300": 320, "1200": 280}
MMP_CURVE_CP = [
    {"duration_s": 120, "power_w": 400},
    {"duration_s": 300, "power_w": 320},
    {"duration_s": 600, "power_w": 280},
]
POWER_JSON = [200 + (i % 40) for i in range(600)]
SIMPLE_WORKOUT = {
    "title": "matrix smoke",
    "steps": [
        {"type": "warmup", "duration_s": 60, "target_w": 160},
        {"type": "work", "duration_s": 120, "target_w": 280, "is_key_step": True},
    ],
}


@dataclass(frozen=True)
class ApiOperation:
    method: str
    path: str
    operation_id: str
    json_schema: Optional[Dict[str, Any]]
    multipart_schema: Optional[Dict[str, Any]]


def load_openapi() -> Dict[str, Any]:
    return json.loads(OPENAPI_JSON.read_text(encoding="utf-8"))


def iter_operations(spec: Optional[Dict[str, Any]] = None) -> List[ApiOperation]:
    spec = spec or load_openapi()
    ops: List[ApiOperation] = []
    for path, item in spec.get("paths", {}).items():
        for method, operation in item.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            request_body = operation.get("requestBody") or {}
            content = request_body.get("content") or {}
            json_schema = (content.get("application/json") or {}).get("schema")
            multipart_schema = (content.get("multipart/form-data") or {}).get("schema")
            ops.append(
                ApiOperation(
                    method=method.upper(),
                    path=path,
                    operation_id=str(operation.get("operationId") or f"{method}_{path}"),
                    json_schema=json_schema,
                    multipart_schema=multipart_schema,
                )
            )
    return ops


def _resolve_ref(schema: Dict[str, Any], components: Dict[str, Any]) -> Dict[str, Any]:
    if "$ref" in schema:
        name = schema["$ref"].split("/")[-1]
        return components.get(name, schema)
    return schema


def _pick_schema_variant(schema: Dict[str, Any], components: Dict[str, Any]) -> Dict[str, Any]:
    schema = _resolve_ref(schema, components)
    if "anyOf" in schema:
        for option in schema["anyOf"]:
            resolved = _resolve_ref(option, components)
            if resolved.get("type") != "null":
                return resolved
        return _resolve_ref(schema["anyOf"][0], components)
    if "oneOf" in schema:
        return _pick_schema_variant(schema["oneOf"][0], components)
    if "allOf" in schema:
        merged: Dict[str, Any] = {"type": "object", "properties": {}, "required": []}
        for part in schema["allOf"]:
            resolved = _pick_schema_variant(part, components)
            if resolved.get("properties"):
                merged["properties"].update(resolved["properties"])
            if resolved.get("required"):
                merged["required"] = list({*merged["required"], *resolved["required"]})
        return merged
    return schema


def minimal_from_schema(
    schema: Optional[Dict[str, Any]],
    components: Dict[str, Any],
    *,
    _depth: int = 0,
) -> Any:
    if schema is None:
        return {}
    if _depth > 8:
        return {}
    schema = _pick_schema_variant(schema, components)
    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]

    schema_type = schema.get("type")
    if schema_type == "object" or "properties" in schema:
        props = schema.get("properties") or {}
        required = schema.get("required") or list(props.keys())
        return {
            key: minimal_from_schema(props[key], components, _depth=_depth + 1)
            for key in required
            if key in props
        }
    if schema_type == "array":
        item_schema = schema.get("items") or {"type": "string"}
        min_items = int(schema.get("minItems") or 1)
        return [minimal_from_schema(item_schema, components, _depth=_depth + 1) for _ in range(min_items)]
    if schema_type == "integer":
        return int(schema.get("minimum") or 1)
    if schema_type == "number":
        return float(schema.get("minimum") or 1.0)
    if schema_type == "boolean":
        return True
    if schema_type == "string":
        if schema.get("format") == "date":
            return "2026-01-15"
        if schema.get("format") == "date-time":
            return "2026-01-15T08:00:00+00:00"
        return "matrix"

    return {}


JSON_PAYLOAD_OVERRIDES: Dict[str, Any] = {
    "profileSnapshot": {"mmp": MMP, "athlete": ATHLETE},
    "profileSnapshotBayesian": {"mmp": MMP, "athlete": ATHLETE, "n_samples": 200, "n_warmup": 50, "seed": 1},
    "profileSnapshotAuto": {"mmp": MMP, "athlete": ATHLETE},
    "profileSnapshotSegmented": {"mmp": MMP, "athlete": ATHLETE},
    "profileSnapshotPhenotype": {"mmp": MMP, "athlete": ATHLETE},
    "profileGlycolyticProfile": {"mmp": MMP, "athlete": ATHLETE},
    "profileCrossValidate": {"mmp": MMP, "athlete": ATHLETE},
    "profileKalmanTrajectory": {
        "athlete": ATHLETE,
        "daily_inputs": [
            {
                "date": "2026-01-01",
                "vo2max_stimulus_min": 10,
                "threshold_stimulus_min": 20,
                "anaerobic_stimulus_min": 5,
                "neuromuscular_stimulus_min": 2,
            }
        ],
        "initial_vo2": 55.0,
        "initial_vla": 0.5,
    },
    "profileMetabolicCurrent": {
        "athlete": ATHLETE,
        "historical_mmp": MMP,
        "workout_history": [{"date": "2026-01-01", "tss": 50}],
        "as_of": "2026-01-15",
    },
    "profileDetrainingApply": {
        "athlete": ATHLETE,
        "baseline_snapshot": {"status": "success", "estimated_vo2max": 55, "mlss_power_watts": 280},
    },
    "profileCtlAtlTsb": {"tss_history": [{"date": "2026-01-01", "tss": 50}]},
    "profileMmpQuality": {"mmp": MMP},
    "profileVlamaxFromSprint": {
        "athlete": ATHLETE,
        "p_peak_1s": 900,
        "p_mean_sprint": 800,
        "sprint_duration_s": 15,
    },
    "profileVlamaxFromPowerSeries": {
        "athlete": ATHLETE,
        "power": POWER_JSON[:15],
        "vo2max_power_w": 400,
    },
    "twinStateBuild": {
        "payload": {
            "athlete_id": "matrix_athlete",
            "weight_kg": 70,
            "ftp_w": 250,
            "cp_w": 270,
            "w_prime_j": 20000,
        }
    },
    "twinStateValidate": {
        "twin_state": {
            "schema_version": "twin_state.v1",
            "athlete_id": "matrix_athlete",
            "athlete_profile": {"weight_kg": 70},
            "metabolic_snapshot": {},
            "rolling_power_curve": MMP,
        }
    },
    "twinStateUpdateFromRide": {
        "twin_state": {"schema_version": "twin_state.v1", "athlete_id": "matrix_athlete"},
        "ride_summary": {"status": "success", "sections": {}},
    },
    "validateWorkout": {"workout": SIMPLE_WORKOUT},
    "prescribeWorkout": {"workout": SIMPLE_WORKOUT, "athlete_profile": {"cp_w": 270, "weight_kg": 70, "w_prime_j": 20000}},
    "feasibilityWorkout": {
        "workout": SIMPLE_WORKOUT,
        "athlete_profile": {"cp_w": 270, "weight_kg": 70, "w_prime_j": 20000},
    },
    "testInPerson": {
        "test_type": "wingate",
        "athlete": {"weight_kg": 70, "sex": "M"},
        "test_data": {"duration_s": 30, "power_stream": [800] * 30},
    },
    "testConfirm": {
        "proposal": {
            "status": "proposed",
            "confidence": 0.8,
            "sprint": {"peak_1s_w": 900, "mean_w": 800, "duration_s": 15},
            "cp_candidates": [],
            "mmp_for_fit": MMP,
            "warnings": [],
            "notes": [],
        },
        "athlete": ATHLETE,
        "measured_on": "2026-01-15",
    },
    "rideUpdateProfile": {
        "ride_mmp": MMP,
        "stored_anchor": {"status": "success", "estimated_vo2max": 55},
        "athlete": ATHLETE,
    },
    "labLactateThresholds": {
        "steps": [
            {"power_w": 200, "lactate_mmol": 2.0},
            {"power_w": 250, "lactate_mmol": 4.0},
        ]
    },
    "labLactateValidateModel": {
        "athlete": ATHLETE,
        "steps": [
            {"power_w": 150, "lactate_mmol": 1.5},
            {"power_w": 180, "lactate_mmol": 2.0},
            {"power_w": 210, "lactate_mmol": 2.8},
            {"power_w": 240, "lactate_mmol": 4.0},
            {"power_w": 270, "lactate_mmol": 6.5},
            {"power_w": 300, "lactate_mmol": 9.0},
        ],
        "mmp": MMP,
    },
    "labVlapeakObserved": {"lactate_pre_mmol": 1.2, "lactate_post_mmol": 8.0, "duration_s": 30},
    "loadManual": {"duration_min": 60, "rpe": 7},
    "historySummary": {"activities": [{"date": "2026-01-01", "tss": 50}]},
    "planningCreateSeasonPlan": {"start_date": "2026-01-01", "target_date": "2026-03-01", "weekly_hours": 8},
    "raceGpxAnalyze": {"gpx_xml": "<gpx version=\"1.1\"></gpx>", "athlete_profile": {"weight_kg": 70, "ftp_w": 250}},
    "raceGpxSimulate": {
        "gpx_xml": "<gpx version=\"1.1\"></gpx>",
        "athlete_profile": {"weight_kg": 70, "ftp_w": 250, "cp_w": 270},
    },
    "rideAnalyticsCriticalPowerFit": {"mmp_curve": MMP_CURVE_CP},
    "rideAnalyticsMetabolicFlexibility": {
        "snapshot": {"fatmax_power_watts": 200, "mlss_power_watts": 280},
    },
    "rideAnalyticsThermalAcclimation": {
        "sessions": [
            {
                "data_quality": "good",
                "thermal_rise_rate": 0.05,
                "n_valid_samples": 100,
                "n_total_samples": 100,
            },
            {
                "data_quality": "good",
                "thermal_rise_rate": 0.04,
                "n_valid_samples": 100,
                "n_total_samples": 100,
            },
            {
                "data_quality": "good",
                "thermal_rise_rate": 0.03,
                "n_valid_samples": 100,
                "n_total_samples": 100,
            },
        ],
    },
    "labParseText": {"text": "VO2max 62.3 ml/kg/min metabolic profile vlamax 0.50"},
    "labValidateResult": {
        "lab_result": {"test_date": "2026-01-15", "vo2max_ml_kg_min": 62.3, "vlamax_mmol_L_s": 0.5},
    },
    "labCreateResult": {"test_date": "2026-01-15", "vo2max": 62.3, "vlamax": 0.5},
    "loadAdaptiveTrend": {
        "history": [{"date": f"2026-01-{day:02d}", "load": 40 + day} for day in range(1, 11)],
    },
    "loadAdaptiveRecommendation": {
        "report": {
            "session_load": {"score": 60},
            "trend": {"load_ratio": 1.0, "tsb": 0},
            "readiness": {"score": 75},
        },
    },
    "explainabilityMetricNarrative": {
        "metric_name": "vo2max",
        "value": 55.0,
        "confidence": {
            "confidence_pct": 80,
            "confidence_level": "HIGH",
            "factors": ["matrix smoke"],
            "limitations": [],
        },
    },
    "explainabilityDurabilityNarrative": {
        "payload": {
            "durability_index": 93.5,
            "classification": "GOOD",
            "confidence": {"confidence_pct": 75, "confidence_level": "MODERATE"},
            "prescription": {
                "focus": "Fine-tune aerobic efficiency",
                "volume": "75-85% Zone 2, 10-15% Zone 3-4, 5% Zone 5+",
                "key_sessions": ["2-3h base rides 3x/week"],
            },
        },
    },
    "metaChartConfig": {"chart_type": "mmp", "payload": {"mmp": MMP}},
}


def json_payload_for_operation(operation: ApiOperation, spec: Dict[str, Any]) -> Dict[str, Any]:
    if operation.operation_id in JSON_PAYLOAD_OVERRIDES:
        return JSON_PAYLOAD_OVERRIDES[operation.operation_id]
    components = spec.get("components", {}).get("schemas", {})
    return minimal_from_schema(operation.json_schema, components)


def _fit_bytes() -> bytes:
    if not FIT_ASSET.is_file():
        raise FileNotFoundError(f"missing FIT asset: {FIT_ASSET}")
    return FIT_ASSET.read_bytes()


def multipart_request_for_operation(operation: ApiOperation) -> Tuple[Dict[str, Any], Dict[str, Tuple[str, bytes, str]]]:
    """Return (form data, files) for multipart operations."""
    fit_bytes = _fit_bytes()
    common_form = {
        "weight_kg": "70",
        "ftp": "250",
        "gender": "MALE",
        "training_years": "10",
        "discipline": "ENDURANCE",
        "power_json": json.dumps(POWER_JSON),
    }
    files: Dict[str, Tuple[str, bytes, str]] = {}

    op = operation.operation_id
    path = operation.path

    if op == "testPropose":
        files["files"] = ("matrix.fit", fit_bytes, "application/octet-stream")
        return {}, files

    if op == "rideIngest":
        files["file"] = ("matrix.fit", fit_bytes, "application/octet-stream")
        return {"ride_date": "2026-01-15", "weight_kg": "70"}, files

    if op == "workoutsCompare":
        return {
            "workout_json": json.dumps(SIMPLE_WORKOUT),
            "athlete_profile_json": json.dumps({"cp_w": 270, "weight_kg": 70, "w_prime_j": 20000}),
            "power_json": json.dumps(POWER_JSON),
        }, files

    if path.startswith("/ride/"):
        files["file"] = ("matrix.fit", fit_bytes, "application/octet-stream")
        return dict(common_form), files

    if op == "performanceNeuromuscularProfile":
        files["file"] = ("matrix.fit", fit_bytes, "application/octet-stream")
        return {"weight_kg": "70"}, files

    files["file"] = ("matrix.fit", fit_bytes, "application/octet-stream")
    return dict(common_form), files


def invalid_json_payload(operation: ApiOperation) -> Dict[str, Any]:
    """Deliberately incomplete payload for negative-path matrix checks."""
    if operation.operation_id in {"profileSnapshot", "profileGlycolyticProfile"}:
        return {"mmp": {}, "athlete": {"weight_kg": 10}}
    if operation.operation_id == "validateWorkout":
        return {"workout": {"steps": []}}
    if operation.operation_id == "planningCreateSeasonPlan":
        return {"start_date": "2026-01-01", "target_date": "2026-03-01", "weekly_hours": -1}
    return {}


STRICT_INVALID_JSON_4XX: frozenset[str] = frozenset(
    {
        "workoutsExport",
        "performanceAbilityProfile",
        "performanceBreakthroughs",
        "planningCreateSeasonPlan",
        "metaChartConfig",
    }
)

NESTED_INVALID_PAYLOADS: Dict[str, Dict[str, Any]] = {
    "metaChartConfig": {"chart_type": "zones", "payload": {}},
}


def nested_invalid_payload(operation: ApiOperation) -> Dict[str, Any]:
    if operation.operation_id in NESTED_INVALID_PAYLOADS:
        return NESTED_INVALID_PAYLOADS[operation.operation_id]
    return invalid_json_payload(operation)
