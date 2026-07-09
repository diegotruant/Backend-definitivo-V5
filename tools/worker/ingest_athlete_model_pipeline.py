#!/usr/bin/env python3
"""
Reference worker pipeline: FIT → MMP aggregate → versioned athlete model → twin.

This script documents the production sequence. It can run locally against
the in-memory stores when SUPABASE_* env vars are unset.

Usage:
    python tools/worker/ingest_athlete_model_pipeline.py /path/to/ride.fit \\
        --athlete-id <uuid> --activity-id <uuid> --activity-file-id <uuid> \\
        --ride-date 2026-06-30 --weight-kg 72

Requires: backend package on PYTHONPATH (run from repo root).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.schemas import AthleteParams
from api.services.ride_service import RideService
from engines.io.fit_parser import parse_fit_file_enhanced
from engines.persistence.metabolic_profile_store import metabolic_profile_store_from_env
from engines.persistence.mmp_aggregate_store import mmp_store_from_env
from engines.persistence.threshold_store import threshold_store_from_env
from engines.twin_state.athlete_model_sync import sync_twin_athlete_model
from engines.twin_state.models import build_twin_state
from engines.twin_state.state_update_engine import update_twin_state_from_ride


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Athlete model ingest worker (reference)")
    parser.add_argument("fit_path", type=Path, help="Path to FIT file")
    parser.add_argument("--athlete-id", required=True)
    parser.add_argument("--activity-id", required=True)
    parser.add_argument("--activity-file-id", required=True)
    parser.add_argument("--ride-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--weight-kg", type=float, default=72.0)
    parser.add_argument("--ftp", type=float, default=None)
    parser.add_argument("--lthr", type=float, default=None)
    parser.add_argument("--stored-curve-json", default=None, help="Optional twin rolling curve JSON")
    parser.add_argument("--twin-state-json", default=None, help="Optional existing twin JSON file")
    parser.add_argument("--dry-run", action="store_true", help="Print summary JSON only")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if not args.fit_path.is_file():
        print(f"FIT not found: {args.fit_path}", file=sys.stderr)
        return 1

    ride_day = date.fromisoformat(args.ride_date)
    stored_curve = json.loads(args.stored_curve_json) if args.stored_curve_json else None
    twin_payload = {}
    if args.twin_state_json:
        twin_payload = json.loads(Path(args.twin_state_json).read_text(encoding="utf-8"))

    stream = parse_fit_file_enhanced(str(args.fit_path), repair_synthetic_header=False)
    athlete = AthleteParams(weight_kg=args.weight_kg)

    service = RideService()
    mmp_store = mmp_store_from_env()
    profile_store = metabolic_profile_store_from_env()
    threshold_store = threshold_store_from_env()

    result = service.process_fit_ingest_with_mmp_aggregate(
        stream=stream,
        ride_date=ride_day,
        file_id=args.fit_path.name,
        file_hash=None,
        weight_kg=args.weight_kg,
        stored_curve=stored_curve,
        athlete_id=args.athlete_id,
        activity_id=args.activity_id,
        activity_file_id=args.activity_file_id,
        ftp=args.ftp,
        lthr=args.lthr,
        athlete=athlete,
        metabolic_snapshot=None,
        hrv_step_seconds=None,
        hrv_max_windows=500,
        mmp_store=mmp_store,
        profile_store=profile_store,
        threshold_store=threshold_store,
    )

    twin = build_twin_state({**twin_payload, "athlete_id": args.athlete_id})
    twin = update_twin_state_from_ride(
        twin,
        ride_summary=result["bundle"].get("workout_summary"),
        ingest_result=result["ingest"],
        ride_id=args.activity_id,
        metabolic_snapshot=None,
    )
    twin = sync_twin_athlete_model(
        twin,
        athlete_id=args.athlete_id,
        mmp_store=mmp_store,
        profile_store=profile_store,
        threshold_store=threshold_store,
        legacy_rolling_curve=result["ingest"].get("curve"),
    )

    output = {
        "mmp_status": result["mmp_aggregate"].get("mmp_status"),
        "metabolic_profile": result["mmp_aggregate"].get("metabolic_profile"),
        "thresholds": result["mmp_aggregate"].get("thresholds"),
        "athlete_model_status": result.get("athlete_model", {}).get("status"),
        "zone_anchors_status": (result.get("zone_anchors") or {}).get("status"),
        "mmp_curve_source": result["ingest"].get("mmp_curve_source"),
        "twin_athlete_model": twin.get("athlete_model"),
        "twin_mmp_source": (twin.get("mmp_curve_meta") or {}).get("source"),
    }

    print(json.dumps(output, indent=2, default=str))
    if args.dry_run:
        return 0

    # Production worker persists:
    # - activities.summary = result["bundle"]
    # - twin_states.twin_state = twin
    # - activity_jobs.status = 'done'
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
