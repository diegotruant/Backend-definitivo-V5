#!/usr/bin/env python3
"""Run the backend over uploaded FIT archives grouped by athlete."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

from engines import (
    AthleteContext,
    MetabolicProfiler,
    assess_data_quality,
    build_workout_summary,
    classify_session,
    cross_validate_metabolic_profile,
    curve_to_mmp,
    parse_fit_file_enhanced,
    update_power_curve,
)
from engines.power_engine import PowerEngine, estimate_ftp_from_mmp, mean_maximal_power


UPLOAD_ROOT = Path("data/fit_uploads")
OUTPUT_DIR = Path("reports/uploaded_fit_analysis")
DEFAULT_WEIGHT_KG = 75.0


def fit_files_by_athlete(root: Path) -> Dict[str, List[Path]]:
    grouped: Dict[str, List[Path]] = defaultdict(list)
    for archive_root in sorted(path for path in root.iterdir() if path.is_dir()):
        for fit_path in sorted(list(archive_root.rglob("*.fit")) + list(archive_root.rglob("*.FIT"))):
            rel = fit_path.relative_to(archive_root)
            athlete = rel.parts[0] if len(rel.parts) > 1 else archive_root.name
            grouped[athlete].append(fit_path)
    return dict(sorted(grouped.items()))


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fields)
        writer.writeheader()
        writer.writerows(rows)


def analyze_athlete(name: str, files: List[Path]) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    parsed = []
    errors: List[Dict[str, Any]] = []
    aggregate_mmp: Dict[int, float] = {}

    for fit_path in files:
        try:
            stream = parse_fit_file_enhanced(str(fit_path))
            parsed.append((fit_path, stream))
            if stream.has_power:
                mmp = mean_maximal_power(np.asarray(stream.power, dtype=float))
                for point in mmp:
                    duration = int(point["duration_s"])
                    aggregate_mmp[duration] = max(aggregate_mmp.get(duration, 0.0), float(point["power_w"]))
        except Exception as exc:
            errors.append({
                "athlete": name,
                "file": fit_path.name,
                "stage": "parse",
                "error_type": type(exc).__name__,
                "error": str(exc),
            })

    ftp_info = estimate_ftp_from_mmp(
        [{"duration_s": d, "power_w": p} for d, p in sorted(aggregate_mmp.items())]
    )
    ftp = float(ftp_info.get("ftp_w") or 250.0)

    stored_curve: Dict[int, Dict[str, Any]] = {}
    activity_rows: List[Dict[str, Any]] = []
    category_counts: Counter[str] = Counter()
    quality_scores: List[float] = []
    total_tss = 0.0
    total_hours = 0.0
    backend_errors = 0

    for fit_path, stream in parsed:
        try:
            power = [float(v) for v in stream.power]
            hr = [float(v) for v in stream.heart_rate] if stream.has_heart_rate else None
            cadence = [float(v) for v in stream.cadence]
            quality = assess_data_quality(power, hr, cadence)
            quality_scores.append(float(quality.overall_score))

            if stream.has_power:
                curve_update = update_power_curve(
                    power,
                    stream.start_time.date().isoformat() if stream.start_time else "unknown",
                    stored_curve,
                    ride_id=fit_path.name,
                    weight_kg=DEFAULT_WEIGHT_KG,
                )
                stored_curve = curve_update.curve

            summary = build_workout_summary(stream, weight_kg=DEFAULT_WEIGHT_KG, ftp=ftp)
            power_section = summary.get("sections", {}).get("power", {})
            metrics = power_section.get("metrics", {})
            classification = classify_session(power, filename=fit_path.name, ftp=ftp)
            category_counts[classification.category] += 1

            duration_h = float(stream.total_elapsed_s or 0.0) / 3600.0
            total_hours += duration_h
            total_tss += float(metrics.get("tss") or 0.0)
            activity_rows.append({
                "athlete": name,
                "file": fit_path.name,
                "has_power": stream.has_power,
                "has_hr": stream.has_heart_rate,
                "has_rr": stream.has_rr,
                "duration_min": round(duration_h * 60.0, 1),
                "avg_power": metrics.get("average_power"),
                "normalized_power": metrics.get("normalized_power"),
                "intensity_factor": metrics.get("intensity_factor"),
                "tss": metrics.get("tss"),
                "avg_hr": round(float(np.mean(stream.heart_rate)), 1) if stream.has_heart_rate else None,
                "quality_score": round(float(quality.overall_score), 3),
                "category": classification.category,
                "subtype": classification.subtype,
                "classification_confidence": round(float(classification.confidence), 3),
                "profile_curve_updated": bool(stream.has_power),
                "backend_status": "success",
            })
        except Exception as exc:
            backend_errors += 1
            errors.append({
                "athlete": name,
                "file": fit_path.name,
                "stage": "backend",
                "error_type": type(exc).__name__,
                "error": str(exc),
            })

    mmp_for_profiler = curve_to_mmp(stored_curve) or aggregate_mmp
    metabolic_status = "not_run"
    metabolic: Dict[str, Any] = {}
    cv_status = "not_run"
    cv: Dict[str, Any] = {}
    if len(mmp_for_profiler) >= 3:
        try:
            profiler = MetabolicProfiler(weight=DEFAULT_WEIGHT_KG, context=AthleteContext())
            metabolic = profiler.generate_metabolic_snapshot(mmp_for_profiler)
            metabolic_status = metabolic.get("status", "unknown")
            unmasked = metabolic.get("unmasked_estimates", {})
            vo2 = unmasked.get("estimated_vo2max") or metabolic.get("estimated_vo2max")
            vla = unmasked.get("estimated_vlamax_mmol_L_s") or metabolic.get("estimated_vlamax_mmol_L_s")
            if vo2 is not None and vla is not None:
                cv_result = cross_validate_metabolic_profile(profiler, mmp_for_profiler, float(vo2), float(vla))
                cv = cv_result.to_dict()
                cv_status = "coherent" if cv_result.coherent else "incoherent"
        except Exception as exc:
            errors.append({
                "athlete": name,
                "file": "",
                "stage": "metabolic_profile",
                "error_type": type(exc).__name__,
                "error": str(exc),
            })
            metabolic_status = "error"

    summary_row = {
        "athlete": name,
        "fit_files": len(files),
        "parsed_files": len(parsed),
        "parse_errors": sum(1 for e in errors if e["stage"] == "parse"),
        "backend_errors": backend_errors,
        "total_duration_h": round(total_hours, 2),
        "total_tss": round(total_tss, 1),
        "ftp_estimate": round(ftp, 1),
        "ftp_method": ftp_info.get("method"),
        "avg_quality_score": round(float(np.mean(quality_scores)), 3) if quality_scores else None,
        "category_counts": json.dumps(dict(category_counts)),
        "mmp_points": len(mmp_for_profiler),
        "metabolic_status": metabolic_status,
        "estimated_vo2max": metabolic.get("estimated_vo2max"),
        "estimated_vlamax": metabolic.get("estimated_vlamax_mmol_L_s"),
        "mlss_power": metabolic.get("mlss_power_watts"),
        "fatmax_power": metabolic.get("fatmax_power_watts"),
        "metabolic_confidence": metabolic.get("confidence_score"),
        "cross_validation_status": cv_status,
        "cross_validation_penalty": cv.get("coherence_penalty"),
        "cross_validation_warnings": json.dumps(cv.get("warnings", [])),
    }
    return summary_row, activity_rows, errors


def write_markdown(path: Path, summary_rows: List[Dict[str, Any]], errors: List[Dict[str, Any]]) -> None:
    total_files = sum(int(row["fit_files"]) for row in summary_rows)
    parsed = sum(int(row["parsed_files"]) for row in summary_rows)
    backend_errors = sum(int(row["backend_errors"]) for row in summary_rows)
    lines = [
        "# Uploaded FIT backend analysis",
        "",
        f"- Athletes: {len(summary_rows)}",
        f"- FIT files discovered: {total_files}",
        f"- FIT files parsed: {parsed}",
        f"- Parse errors: {sum(int(row['parse_errors']) for row in summary_rows)}",
        f"- Backend errors: {backend_errors}",
        "",
        "## Athlete summary",
        "",
        "| Athlete | FIT | FTP W | TSS | Quality | Metabolic | Cross-validation |",
        "| --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in summary_rows:
        lines.append(
            f"| {row['athlete']} | {row['parsed_files']}/{row['fit_files']} | "
            f"{row['ftp_estimate']} | {row['total_tss']} | {row['avg_quality_score']} | "
            f"{row['metabolic_status']} | {row['cross_validation_status']} |"
        )
    lines.extend(["", "## Errors", ""])
    if errors:
        for err in errors:
            lines.append(f"- `{err['athlete']}/{err['file']}` [{err['stage']}]: {err['error_type']} - {err['error']}")
    else:
        lines.append("No parsing or backend exceptions detected.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    grouped = fit_files_by_athlete(UPLOAD_ROOT)
    summary_rows: List[Dict[str, Any]] = []
    activity_rows: List[Dict[str, Any]] = []
    error_rows: List[Dict[str, Any]] = []
    for i, (athlete, files) in enumerate(grouped.items(), 1):
        print(f"[{i:02d}/{len(grouped)}] {athlete} ({len(files)} FIT)")
        summary, activities, errors = analyze_athlete(athlete, files)
        summary_rows.append(summary)
        activity_rows.extend(activities)
        error_rows.extend(errors)

    write_csv(OUTPUT_DIR / "athlete_summary.csv", summary_rows)
    write_csv(OUTPUT_DIR / "activity_details.csv", activity_rows)
    write_csv(OUTPUT_DIR / "errors.csv", error_rows)
    write_markdown(OUTPUT_DIR / "README.md", summary_rows, error_rows)
    print(f"Wrote {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
