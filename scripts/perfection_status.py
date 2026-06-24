#!/usr/bin/env python3
"""Print progress toward tests/perfection_manifest.json targets."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
MANIFEST = ROOT / "tests" / "perfection_manifest.json"
BASELINE = ROOT / "tests" / "coverage_baseline.json"
COVERAGE = ROOT / "coverage.json"

FORBIDDEN_STATUSES = frozenset({"error", "failed", "internal_error"})


def _matrix_ratios() -> tuple[float, float, int]:
    from fastapi.testclient import TestClient

    from api_app import app
    from tests.openapi_matrix_support import (
        iter_operations,
        json_payload_for_operation,
        load_openapi,
        multipart_request_for_operation,
        nested_invalid_payload,
    )

    client = TestClient(app)
    spec = load_openapi()
    valid_ok = valid_total = invalid_ok = invalid_total = 0

    for op in iter_operations(spec):
        if op.json_schema is not None:
            invalid_total += 1
            payload = nested_invalid_payload(op)
            response = client.request(op.method, op.path, json=payload)
            if 400 <= response.status_code < 500:
                invalid_ok += 1

        if op.method == "GET":
            response = client.get(op.path)
        elif op.multipart_schema is not None:
            data, files = multipart_request_for_operation(op)
            response = client.post(op.path, data=data, files=files or None)
        elif op.json_schema is not None:
            payload = json_payload_for_operation(op, spec)
            response = client.request(op.method, op.path, json=payload)
        else:
            continue

        valid_total += 1
        if response.status_code != 200:
            continue
        if "application/json" not in response.headers.get("content-type", ""):
            valid_ok += 1
            continue
        body = response.json()
        status = body.get("status")
        if status is None or str(status) not in FORBIDDEN_STATUSES:
            valid_ok += 1

    valid_ratio = valid_ok / valid_total if valid_total else 0.0
    invalid_ratio = invalid_ok / invalid_total if invalid_total else 0.0
    return valid_ratio, invalid_ratio, valid_total


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    phase_id = manifest.get("current_phase", 1)
    phase = next(p for p in manifest["phases"] if p["id"] == phase_id)

    print(f"Perfection program — phase {phase_id}: {phase['name']} ({phase.get('status', '?')})")
    print()

    targets = phase.get("targets", {})
    if COVERAGE.is_file() and BASELINE.is_file():
        cov = json.loads(COVERAGE.read_text(encoding="utf-8"))["totals"]
        base = json.loads(BASELINE.read_text(encoding="utf-8"))
        line = float(cov["percent_covered"])
        branch = float(cov["percent_branches_covered"])
        t_line = targets.get("coverage_line_percent")
        t_branch = targets.get("coverage_branch_percent")
        if t_line is not None:
            print(f"  line coverage:   {line:5.1f}%  (phase target {t_line}%, baseline floor {base['line_percent']}%)")
        if t_branch is not None:
            print(f"  branch coverage: {branch:5.1f}%  (phase target {t_branch}%, baseline floor {base['branch_percent']}%)")

    try:
        valid_ratio, invalid_ratio, n_ops = _matrix_ratios()
        t_valid = targets.get("matrix_valid_must_success_ratio")
        t_invalid = targets.get("matrix_invalid_must_4xx_ratio")
        if t_valid is not None:
            mark = "OK" if valid_ratio >= float(t_valid) else "below target"
            print(f"  matrix valid must-success: {valid_ratio:5.1%}  (target {float(t_valid):.0%}, {n_ops} ops) — {mark}")
        if t_invalid is not None:
            mark = "OK" if invalid_ratio >= float(t_invalid) else "below target"
            print(f"  matrix invalid must-4xx:   {invalid_ratio:5.1%}  (target {float(t_invalid):.0%}) — {mark}")
    except Exception as exc:  # pragma: no cover - status helper must not break CI
        print(f"  matrix ratios: unavailable ({exc})")

    for key, value in targets.items():
        if key.startswith("coverage_") or key.startswith("matrix_"):
            continue
        print(f"  {key}: target {value}")

    print()
    print("Deliverables this phase:")
    for item in phase.get("deliverables", []):
        print(f"  - {item}")

    next_phases = [p for p in manifest["phases"] if p["id"] > phase_id]
    if next_phases:
        nxt = next_phases[0]
        print()
        print(f"Next phase ({nxt['id']}): {nxt['name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
