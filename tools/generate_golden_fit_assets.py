#!/usr/bin/env python3
"""Generate golden FIT binaries and expected parse snapshots for CI.

Uses garmin-fit-sdk in an isolated pip install. Run from repo root:

    python tools/generate_golden_fit_assets.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "tests" / "assets" / "fit"
GENERATOR = REPO / "tools" / "_golden_fit_builder.py"


def _ensure_sdk() -> None:
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "garmin-fit-sdk", "-q"],
        cwd=REPO,
    )


def _run_builder() -> None:
    subprocess.check_call([sys.executable, str(GENERATOR)], cwd=REPO)


def _write_expected_snapshots() -> None:
    sys.path.insert(0, str(REPO))
    from engines.io.fit_parse_report import build_fit_parse_report
    from engines.io.fit_parser import measured_signal_flags, parse_fit_file_enhanced
    from tools.golden_fit_coach_snapshot import build_coach_golden_snapshot

    for fit_path in sorted(OUT_DIR.glob("*.fit")):
        if fit_path.stem in {"truncated", "bad_crc"}:
            continue
        try:
            stream = parse_fit_file_enhanced(str(fit_path), repair_synthetic_header=False)
        except Exception as exc:
            print(f"skip snapshot for {fit_path.name}: {exc}")
            continue
        measured = measured_signal_flags(stream)
        report = build_fit_parse_report(stream=stream, file_id=fit_path.stem, file_hash="golden")
        snapshot = {
            "file": fit_path.name,
            "parser_version": report["parser_version"],
            "duration_s": report["duration_s"],
            "measured_signals": measured,
            "available_signals": sorted(report["available_signals"]),
            "lap_count": len(report.get("laps") or []),
            "has_power_stream": measured["power"],
            "has_hr_stream": measured["heart_rate"],
            "has_cadence_stream": measured["cadence"],
            "has_speed_stream": measured["speed"],
            "warnings": report.get("warnings") or [],
        }
        if report.get("laps"):
            snapshot["first_lap"] = {
                "duration_s": report["laps"][0].get("duration_s"),
                "avg_power_w": report["laps"][0].get("avg_power_w"),
            }
        out = OUT_DIR / f"{fit_path.stem}.expected_parse.json"
        out.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {out.relative_to(REPO)}")

        coach = build_coach_golden_snapshot(fit_path, stream)
        coach_out = OUT_DIR / f"{fit_path.stem}.expected_coach.json"
        coach_out.write_text(json.dumps(coach, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {coach_out.relative_to(REPO)}")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _ensure_sdk()
    _run_builder()
    _write_expected_snapshots()
    subprocess.call([sys.executable, "-m", "pip", "uninstall", "-y", "garmin-fit-sdk", "tests"], cwd=REPO)


if __name__ == "__main__":
    main()
