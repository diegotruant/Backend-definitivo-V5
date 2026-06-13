"""Minimal synthetic FIT-like binary files for parser regression tests."""

from __future__ import annotations

import struct
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Tuple

import numpy as np

from engines.io.fit_parser import ActivityStreamEnhanced

Record = Tuple[int, int, int, int]  # unix_ts, power_w, hr_bpm, cadence_rpm

HEADER_SIZE = 12
RECORD_STRIDE = 15


def _validate_records(records: List[Record]) -> None:
    if len(records) < 2:
        raise ValueError("Need at least 2 records")
    for ts, power, hr, cadence in records:
        if not (1_500_000_000 <= ts <= 2_500_000_000):
            raise ValueError(f"timestamp out of range: {ts}")
        if not (0 <= power <= 2500):
            raise ValueError(f"power out of range: {power}")
        if not (30 <= hr <= 230):
            raise ValueError(f"hr out of range: {hr}")
        if not (0 <= cadence <= 220):
            raise ValueError(f"cadence out of range: {cadence}")


def build_synthetic_fit_bytes(records: List[Record]) -> bytes:
    """Encode records in the layout expected by parse_synthetic_fit()."""
    _validate_records(records)
    buf = bytearray(b"\x00" * HEADER_SIZE)
    for ts, power, hr, cadence in records:
        row = bytearray(RECORD_STRIDE)
        row[0] = 0
        struct.pack_into("<I", row, 1, ts)
        struct.pack_into("<H", row, 5, power)
        row[7] = hr
        row[8] = cadence
        buf.extend(row)
    return bytes(buf)


def parse_synthetic_fit(raw: bytes) -> ActivityStreamEnhanced:
    """Parse synthetic FIT-like bytes into ActivityStreamEnhanced."""
    offset = HEADER_SIZE
    stride = RECORD_STRIDE
    records: List[Record] = []
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
        if not (1_500_000_000 <= ts <= 2_500_000_000):
            break
        records.append((ts, power, hr, cadence))
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

    return stream


def write_synthetic_fit(path: Path, records: Iterable[Record]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_synthetic_fit_bytes(list(records)))
    return path


def sample_endurance_records(duration_s: int = 600, *, start_ts: int = 1_735_689_600) -> List[Record]:
    """1 Hz endurance block with mild climb encoded via speed/altitude added later."""
    out: List[Record] = []
    for i in range(0, duration_s + 1, 60):
        power = 220 + (i // 60) % 5 * 5
        hr = 140 + (i // 120)
        cadence = 90 + (i // 60) % 3
        out.append((start_ts + i, power, hr, cadence))
    return out
