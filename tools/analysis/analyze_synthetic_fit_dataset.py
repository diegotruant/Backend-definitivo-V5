#!/usr/bin/env python3
"""Analyze the synthetic FIT dataset athlete-by-athlete."""

from __future__ import annotations

import csv
import json
import struct
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np

from engines.core.athlete_context import AthleteContext
from engines.core.data_quality_engine import assess_data_quality
from engines.io.workout_summary import build_workout_summary
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from engines.performance.durability_engine import calculate_durability_index, calculate_np_drift
from engines.performance.interval_detector import classify_session
from engines.io.fit_parser import ActivityStreamEnhanced
from engines.performance.power_engine import estimate_ftp_from_mmp, mean_maximal_power


DEFAULT_DATASET = Path("data/synthetic_fit_dataset")
DEFAULT_OUTPUT = Path("reports/synthetic_fit_analysis")
WEIGHT_KG = 75.0


@dataclass
class ParsedSyntheticFit:
    path: Path
    stream: ActivityStreamEnhanced
    record_count: int
    parser_note: str


def _candidate_records(raw: bytes, offset: int, stride: int, n: int = 5) -> Optional[List[Tuple[int, int, int, int]]]:
    records = []
    for i in range(n):
        pos = offset + i * stride
        if pos + 9 > len(raw):
            return None
        if raw[pos] != 0:
            return None
        ts = struct.unpack_from("<I", raw, pos + 1)[0]
        power = struct.unpack_from("<H", raw, pos + 5)[0]
        hr = raw[pos + 7]
        cadence = raw[pos + 8]
        if not (1577836800 <= ts <= 2208988800):
            return None
        power_ok = 0 <= power <= 2500 or power == 65535
        hr_ok = 30 <= hr <= 230 or hr == 255
        cadence_ok = 0 <= cadence <= 220 or cadence == 255
        if not (power_ok and hr_ok and cadence_ok):
            return None
        records.append((ts, power, hr, cadence))
    deltas = [records[i + 1][0] - records[i][0] for i in range(len(records) - 1)]
    if not all(1 <= d <= 300 for d in deltas):
        return None
    return records


def _find_record_layout(raw: bytes) -> Tuple[int, int]:
    for stride in (15, 16, 14, 13, 12):
        for offset in range(12, min(256, len(raw) - stride * 5)):
            if _candidate_records(raw, offset, stride) is not None:
                return offset, stride
    raise ValueError("Could not locate synthetic record layout")


def parse_synthetic_fit(path: Path) -> ParsedSyntheticFit:
    """Parse the known synthetic FIT-like files into ActivityStreamEnhanced."""
    raw = path.read_bytes()
    offset, stride = _find_record_layout(raw)

    records: List[Tuple[int, int, int, int]] = []
    pos = offset
    while pos + 9 <= len(raw):
        if raw[pos] != 0:
            break
        ts = struct.unpack_from("<I", raw, pos + 1)[0]
        power = struct.unpack_from("<H", raw, pos + 5)[0]
        hr = raw[pos + 7]
        cadence = raw[pos + 8]
        if records and not (0 < ts - records[-1][0] <= 300):
            break
        if not (1577836800 <= ts <= 2208988800):
            break
        power_ok = 0 <= power <= 2500 or power == 65535
        hr_ok = 30 <= hr <= 230 or hr == 255
        cadence_ok = 0 <= cadence <= 220 or cadence == 255
        if not (power_ok and hr_ok and cadence_ok):
            break
        records.append((
            ts,
            0 if power == 65535 else power,
            0 if hr == 255 else hr,
            0 if cadence == 255 else cadence,
        ))
        pos += stride

    if len(records) < 2:
        raise ValueError("Synthetic parser found fewer than 2 records")

    start_ts = records[0][0]
    end_ts = records[-1][0]
    total_elapsed_s = int(end_ts - start_ts)
    n_samples = total_elapsed_s + 1

    stream = ActivityStreamEnhanced(
        n_samples=n_samples,
        sport="cycling",
        start_time=datetime.fromtimestamp(start_ts, timezone.utc),
        total_elapsed_s=float(total_elapsed_s),
    )
    stream.elapsed_s = np.arange(n_samples, dtype=np.float32)

    for i, (ts, power, hr, cadence) in enumerate(records):
        start = int(ts - start_ts)
        if i + 1 < len(records):
            end = int(records[i + 1][0] - start_ts)
        else:
            end = n_samples
        end = max(start + 1, min(end, n_samples))
        stream.power[start:end] = float(power)
        stream.heart_rate[start:end] = float(hr)
        stream.cadence[start:end] = float(cadence)

    stream.gap_summary = {
        "source": "synthetic_binary_parser",
        "record_offset": offset,
        "record_stride": stride,
        "record_count": len(records),
    }
    return ParsedSyntheticFit(
        path=path,
        stream=stream,
        record_count=len(records),
        parser_note=f"synthetic_binary_parser(offset={offset}, stride={stride})",
    )


def _aggregate_mmp(best: Dict[int, float], mmp_curve: Iterable[Dict[str, float]]) -> None:
    for point in mmp_curve:
        duration = int(point["duration_s"])
        power = float(point["power_w"])
        best[duration] = max(best.get(duration, 0.0), power)


def _mmp_list(best: Dict[int, float]) -> List[Dict[str, float]]:
    return [
        {"duration_s": int(duration), "power_w": round(power, 1)}
        for duration, power in sorted(best.items())
    ]


def _metabolic_snapshot(best_mmp: Dict[int, float], weight_kg: float) -> Dict[str, object]:
    if len(best_mmp) < 3:
        return {"status": "insufficient_mmp"}
    profiler = MetabolicProfiler(weight=weight_kg, context=AthleteContext())
    mmp_dict = {int(k): float(v) for k, v in best_mmp.items()}
    return profiler.generate_metabolic_snapshot(mmp_dict)


def analyze_athlete(athlete_dir: Path) -> Tuple[Dict[str, object], List[Dict[str, object]]]:
    fit_files = sorted(athlete_dir.glob("*.fit"))
    parsed_cache: List[ParsedSyntheticFit] = []
    errors: List[str] = []
    aggregate_mmp: Dict[int, float] = {}

    for fit_path in fit_files:
        try:
            parsed = parse_synthetic_fit(fit_path)
            parsed_cache.append(parsed)
            mmp = mean_maximal_power(np.asarray(parsed.stream.power, dtype=float))
            _aggregate_mmp(aggregate_mmp, mmp)
        except Exception as exc:
            errors.append(f"{fit_path.name}: {type(exc).__name__}: {exc}")

    ftp_info = estimate_ftp_from_mmp(_mmp_list(aggregate_mmp))
    ftp = float(ftp_info["ftp_w"] or 250.0)

    file_rows: List[Dict[str, object]] = []
    category_counts: Counter[str] = Counter()
    subtype_counts: Counter[str] = Counter()
    total_tss = 0.0
    total_duration_h = 0.0
    quality_scores: List[float] = []
    avg_powers: List[float] = []
    avg_hrs: List[float] = []
    np_values: List[float] = []
    if_values: List[float] = []
    durability_values: List[float] = []

    for parsed in parsed_cache:
        stream = parsed.stream
        power_values = [float(v) for v in stream.power]
        hr_values = [float(v) for v in stream.heart_rate]
        cadence_values = [float(v) for v in stream.cadence]
        quality = assess_data_quality(power_values, hr_values, cadence_values)
        quality_scores.append(float(quality.overall_score))

        summary = build_workout_summary(stream, weight_kg=WEIGHT_KG, ftp=ftp)
        power_section = summary.get("sections", {}).get("power", {})
        metrics = power_section.get("metrics", {})

        classification = classify_session(
            power_values,
            filename=parsed.path.name,
            laps=None,
            ftp=ftp,
        )
        category_counts[classification.category] += 1
        subtype_counts[classification.subtype] += 1

        duration_h = float(stream.total_elapsed_s or 0.0) / 3600.0
        total_duration_h += duration_h
        total_tss += float(metrics.get("tss") or 0.0)
        avg_powers.append(float(metrics.get("average_power") or 0.0))
        avg_hrs.append(float(np.mean(stream.heart_rate)) if stream.has_heart_rate else 0.0)
        np_values.append(float(metrics.get("normalized_power") or 0.0))
        if_values.append(float(metrics.get("intensity_factor") or 0.0))

        durability = calculate_durability_index(power_values, int(stream.total_elapsed_s or len(power_values)))
        if durability.get("status") == "success":
            durability_values.append(float(durability["durability_index"]))

        np_drift = calculate_np_drift(power_values, int(stream.total_elapsed_s or len(power_values)))

        file_rows.append({
            "athlete": athlete_dir.name,
            "file": parsed.path.name,
            "parsed": True,
            "duration_min": round(duration_h * 60.0, 1),
            "ftp_used": ftp,
            "avg_power": metrics.get("average_power"),
            "normalized_power": metrics.get("normalized_power"),
            "intensity_factor": metrics.get("intensity_factor"),
            "tss": metrics.get("tss"),
            "avg_hr": round(float(np.mean(stream.heart_rate)), 1) if stream.has_heart_rate else None,
            "max_power": metrics.get("max_power"),
            "quality_score": round(float(quality.overall_score), 3),
            "category": classification.category,
            "subtype": classification.subtype,
            "classification_confidence": round(float(classification.confidence), 3),
            "durability_index": durability.get("durability_index"),
            "np_drift_pct": np_drift.get("np_drift_pct"),
            "parser_note": parsed.parser_note,
            "error": "",
        })

    for err in errors:
        file_rows.append({
            "athlete": athlete_dir.name,
            "file": err.split(":", 1)[0],
            "parsed": False,
            "error": err,
        })

    metabolic = _metabolic_snapshot(aggregate_mmp, WEIGHT_KG)
    summary_row: Dict[str, object] = {
        "athlete": athlete_dir.name,
        "fit_files": len(fit_files),
        "parsed_files": len(parsed_cache),
        "error_files": len(errors),
        "total_duration_h": round(total_duration_h, 2),
        "ftp_estimate": round(ftp, 1),
        "ftp_method": ftp_info.get("method"),
        "total_tss": round(total_tss, 1),
        "avg_tss_per_file": round(total_tss / len(parsed_cache), 1) if parsed_cache else None,
        "avg_power": round(float(np.mean(avg_powers)), 1) if avg_powers else None,
        "avg_normalized_power": round(float(np.mean(np_values)), 1) if np_values else None,
        "avg_intensity_factor": round(float(np.mean(if_values)), 3) if if_values else None,
        "avg_hr": round(float(np.mean(avg_hrs)), 1) if avg_hrs else None,
        "avg_quality_score": round(float(np.mean(quality_scores)), 3) if quality_scores else None,
        "avg_durability_index": round(float(np.mean(durability_values)), 1) if durability_values else None,
        "category_counts": json.dumps(dict(sorted(category_counts.items()))),
        "top_subtypes": json.dumps(dict(subtype_counts.most_common(5))),
        "best_5s": round(aggregate_mmp.get(5, 0.0), 1),
        "best_1min": round(aggregate_mmp.get(60, 0.0), 1),
        "best_5min": round(aggregate_mmp.get(300, 0.0), 1),
        "best_20min": round(aggregate_mmp.get(1200, 0.0), 1),
        "best_60min": round(aggregate_mmp.get(3600, 0.0), 1),
        "metabolic_status": metabolic.get("status"),
        "estimated_vo2max": metabolic.get("estimated_vo2max"),
        "estimated_vlamax": metabolic.get("estimated_vlamax_mmol_L_s"),
        "mlss_power": metabolic.get("mlss_power_watts"),
        "fatmax_power": metabolic.get("fatmax_power_watts"),
        "metabolic_confidence": metabolic.get("confidence_score"),
    }
    return summary_row, file_rows


def write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path: Path, athlete_rows: List[Dict[str, object]], file_rows: List[Dict[str, object]]) -> None:
    parsed = sum(int(row.get("parsed_files", 0)) for row in athlete_rows)
    errors = sum(int(row.get("error_files", 0)) for row in athlete_rows)
    total_tss = sum(float(row.get("total_tss") or 0.0) for row in athlete_rows)
    total_hours = sum(float(row.get("total_duration_h") or 0.0) for row in athlete_rows)
    avg_quality = np.mean([float(row["avg_quality_score"]) for row in athlete_rows if row.get("avg_quality_score") is not None])

    strongest = sorted(athlete_rows, key=lambda r: float(r.get("ftp_estimate") or 0.0), reverse=True)[:10]
    best_vo2 = sorted(
        [r for r in athlete_rows if r.get("estimated_vo2max") is not None],
        key=lambda r: float(r.get("estimated_vo2max") or 0.0),
        reverse=True,
    )[:10]

    lines = [
        "# Synthetic FIT dataset analysis",
        "",
        "Generated with `analyze_synthetic_fit_dataset.py` using the backend engines.",
        "",
        "## Dataset summary",
        "",
        f"- Athletes: {len(athlete_rows)}",
        f"- FIT files parsed: {parsed}",
        f"- FIT files with errors: {errors}",
        f"- Total analyzed duration: {total_hours:.1f} h",
        f"- Total TSS: {total_tss:.1f}",
        f"- Mean data quality score: {avg_quality:.3f}",
        "",
        "## Top 10 by estimated FTP",
        "",
        "| Athlete | FTP W | Best 20 min W | Total TSS | Avg quality | Metabolic status |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in strongest:
        lines.append(
            f"| {row['athlete']} | {row['ftp_estimate']} | {row['best_20min']} | "
            f"{row['total_tss']} | {row['avg_quality_score']} | {row['metabolic_status']} |"
        )

    lines.extend([
        "",
        "## Top 10 by estimated VO2max",
        "",
        "| Athlete | VO2max | VLamax | MLSS W | FatMax W | Confidence |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ])
    for row in best_vo2:
        lines.append(
            f"| {row['athlete']} | {row['estimated_vo2max']} | {row['estimated_vlamax']} | "
            f"{row['mlss_power']} | {row['fatmax_power']} | {row['metabolic_confidence']} |"
        )

    lines.extend([
        "",
        "## Notes",
        "",
        "- The source files are synthetic and required a lightweight synthetic binary parser.",
        "- Power/HR/cadence records are expanded to a 1 Hz timeline before running the backend.",
        "- Metabolic estimates are model-derived from aggregate MMP per athlete and are not lab validated.",
        "- Detailed per-athlete and per-file outputs are in the CSV files next to this report.",
        "",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: List[str]) -> int:
    dataset = Path(argv[1]) if len(argv) > 1 else DEFAULT_DATASET
    output = Path(argv[2]) if len(argv) > 2 else DEFAULT_OUTPUT
    if not dataset.exists():
        print(f"Dataset not found: {dataset}", file=sys.stderr)
        return 2

    athlete_dirs = sorted(path for path in dataset.iterdir() if path.is_dir())
    athlete_rows: List[Dict[str, object]] = []
    file_rows: List[Dict[str, object]] = []

    for idx, athlete_dir in enumerate(athlete_dirs, 1):
        print(f"[{idx:02d}/{len(athlete_dirs)}] {athlete_dir.name}")
        summary_row, rows = analyze_athlete(athlete_dir)
        athlete_rows.append(summary_row)
        file_rows.extend(rows)

    write_csv(output / "athlete_summary.csv", athlete_rows)
    write_csv(output / "activity_details.csv", file_rows)
    write_markdown(output / "README.md", athlete_rows, file_rows)
    print(f"Wrote reports to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
