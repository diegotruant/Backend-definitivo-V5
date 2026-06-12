#!/usr/bin/env python3
"""Deep bottleneck finder for Backend-definitivo-V5.1.

Goes where the HTTP stress test cannot: isolates compute hotspots, monitors
memory under sustained load, generates real FIT binary uploads, tests
concurrent twin_state mutations on the same athlete, and feeds pathological
inputs to find worst-case engine behaviour.

Run modes:
    python tools/stress/deep_bottleneck.py --mode all          # full suite
    python tools/stress/deep_bottleneck.py --mode profiler     # ODE solver only
    python tools/stress/deep_bottleneck.py --mode memory       # RSS watermark
    python tools/stress/deep_bottleneck.py --mode fit-upload   # binary FIT path
    python tools/stress/deep_bottleneck.py --mode contention   # same-athlete race
    python tools/stress/deep_bottleneck.py --mode pathological # edge-case fuzzer

Requires a running server (--base-url) for HTTP modes; profiler/memory modes
import engines directly and run in-process.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import io
import json
import math
import os
import random
import struct
import sys
import tempfile
import time
import traceback

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# Ensure repository root is importable when this script is executed as
# `python tools/stress/deep_bottleneck.py` without PYTHONPATH=.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _mb(nbytes: int) -> float:
    return round(nbytes / (1024 * 1024), 2)


def _rss_mb() -> float:
    """Current process RSS in MB. Falls back to 0 if psutil unavailable."""
    try:
        import psutil
        return _mb(psutil.Process(os.getpid()).memory_info().rss)
    except ImportError:
        try:
            with open("/proc/self/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        return round(int(line.split()[1]) / 1024, 2)
        except Exception:
            pass
    return 0.0


@dataclass
class BenchResult:
    name: str
    iterations: int
    total_s: float
    mean_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float
    min_ms: float
    rss_start_mb: float = 0.0
    rss_peak_mb: float = 0.0
    rss_end_mb: float = 0.0
    errors: int = 0
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v or isinstance(v, (int, float))}


def _percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    rank = (len(s) - 1) * p
    lo, hi = math.floor(rank), math.ceil(rank)
    return s[lo] + (s[hi] - s[lo]) * (rank - lo) if lo != hi else s[lo]


def _bench(name: str, fn: Callable[[], Any], iterations: int, *, warmup: int = 1) -> BenchResult:
    """Run fn iterations times, collect timings and RSS."""
    for _ in range(warmup):
        try:
            fn()
        except Exception:
            pass
    gc.collect()
    rss_start = _rss_mb()
    rss_peak = rss_start
    timings: List[float] = []
    errors = 0
    for i in range(iterations):
        t0 = time.perf_counter()
        try:
            fn()
        except Exception:
            errors += 1
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        timings.append(elapsed_ms)
        if (i + 1) % max(1, iterations // 10) == 0:
            rss_peak = max(rss_peak, _rss_mb())
    gc.collect()
    rss_end = _rss_mb()
    rss_peak = max(rss_peak, rss_end)
    return BenchResult(
        name=name,
        iterations=iterations,
        total_s=round(sum(timings) / 1000.0, 3),
        mean_ms=round(sum(timings) / len(timings), 2) if timings else 0,
        p50_ms=round(_percentile(timings, 0.50), 2),
        p95_ms=round(_percentile(timings, 0.95), 2),
        p99_ms=round(_percentile(timings, 0.99), 2),
        max_ms=round(max(timings), 2) if timings else 0,
        min_ms=round(min(timings), 2) if timings else 0,
        rss_start_mb=rss_start,
        rss_peak_mb=rss_peak,
        rss_end_mb=rss_end,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# 1. PROFILER MICROBENCHMARK
# ---------------------------------------------------------------------------

def _make_mmp(rng: random.Random, *, n_points: int = 7, cp_range: Tuple[float, float] = (180, 350)) -> Dict[str, float]:
    cp = rng.uniform(*cp_range)
    durations = [1, 5, 15, 30, 60, 120, 300, 600, 1200, 1800, 3600][:n_points]
    mmp: Dict[str, float] = {}
    for d in durations:
        # Hyperbolic-ish: power = cp + W'/d, with noise
        w_prime = rng.uniform(10000, 30000)
        p = cp + w_prime / max(d, 1) + rng.gauss(0, 8)
        mmp[str(d)] = round(max(50, p), 1)
    return mmp


def _make_athlete_ctx(rng: random.Random) -> Tuple[float, "AthleteContext"]:
    from engines.core.athlete_context import AthleteContext
    weight = rng.uniform(55, 92)
    ctx = AthleteContext(
        gender=rng.choice(["MALE", "FEMALE"]),
        training_years=rng.randint(2, 20),
        discipline=rng.choice(["ENDURANCE", "ROAD", "SPRINT", "GRAVEL"]),
    )
    return weight, ctx


def run_profiler_bench(iterations: int = 20, seed: int = 42) -> List[BenchResult]:
    from engines.metabolic.metabolic_profiler import MetabolicProfiler
    rng = random.Random(seed)
    results: List[BenchResult] = []

    # Scenario A: normal 7-point MMP (typical coach usage)
    w_a, ctx_a = _make_athlete_ctx(rng)
    mmp_a = _make_mmp(rng, n_points=7)
    profiler_a = MetabolicProfiler(w_a, ctx_a)
    results.append(_bench(
        "profiler_7pt_normal",
        lambda: profiler_a.generate_metabolic_snapshot(mmp_a),
        iterations,
    ))

    # Scenario B: dense 11-point MMP (power-meter with many durations)
    w_b, ctx_b = _make_athlete_ctx(rng)
    mmp_b = _make_mmp(rng, n_points=11)
    profiler_b = MetabolicProfiler(w_b, ctx_b)
    results.append(_bench(
        "profiler_11pt_dense",
        lambda: profiler_b.generate_metabolic_snapshot(mmp_b),
        iterations,
    ))

    # Scenario C: extreme sprinter phenotype (high short, low long — worst-case for solver)
    from engines.core.athlete_context import AthleteContext
    mmp_c = {"1": 1650.0, "5": 1100.0, "15": 680.0, "60": 410.0, "300": 280.0, "1200": 225.0, "3600": 195.0}
    ctx_c = AthleteContext(gender="MALE", discipline="SPRINT", training_years=8)
    profiler_c = MetabolicProfiler(92.0, ctx_c)
    results.append(_bench(
        "profiler_sprinter_extreme",
        lambda: profiler_c.generate_metabolic_snapshot(mmp_c),
        iterations,
    ))

    # Scenario D: very weak athlete (low absolute values — can trigger solver edge cases)
    mmp_d = {"1": 450.0, "5": 320.0, "15": 240.0, "60": 175.0, "300": 135.0, "1200": 115.0, "3600": 100.0}
    ctx_d = AthleteContext(gender="FEMALE", discipline="ENDURANCE", training_years=2)
    profiler_d = MetabolicProfiler(52.0, ctx_d)
    results.append(_bench(
        "profiler_weak_athlete",
        lambda: profiler_d.generate_metabolic_snapshot(mmp_d),
        iterations,
    ))

    # Scenario E: with mmp_quality cleaning enabled (adds overhead)
    w_e, ctx_e = _make_athlete_ctx(rng)
    mmp_e = _make_mmp(rng, n_points=11)
    samples_e = [{"duration_s": int(k), "power_w": v, "filename": f"ride_{i}.fit", "date": "2026-05-01"}
                 for i, (k, v) in enumerate(mmp_e.items())]
    profiler_e = MetabolicProfiler(w_e, ctx_e)
    results.append(_bench(
        "profiler_11pt_with_quality_clean",
        lambda: profiler_e.generate_metabolic_snapshot(mmp_e, clean_mmp_first=True, mmp_samples=samples_e),
        iterations,
    ))

    return results


# ---------------------------------------------------------------------------
# 2. MEMORY WATERMARK UNDER SUSTAINED LOAD
# ---------------------------------------------------------------------------

def run_memory_bench(iterations: int = 50, seed: int = 42) -> List[BenchResult]:
    """Sustained in-process calls tracking RSS growth and GC pressure."""
    from engines.metabolic.metabolic_profiler import MetabolicProfiler
    from engines.io.workout_summary import build_workout_summary
    from engines.projection.season_projection_engine import project_season_from_plan
    from engines.twin_state.models import build_twin_state

    rng = random.Random(seed)
    results: List[BenchResult] = []

    # Sustained profiler calls — does RSS climb or stay flat?
    w, ctx = _make_athlete_ctx(rng)
    profiler = MetabolicProfiler(w, ctx)

    def sustained_profiler():
        mmp = _make_mmp(rng, n_points=7)
        profiler.generate_metabolic_snapshot(mmp)

    r = _bench("memory_sustained_profiler", sustained_profiler, iterations)
    r.notes = f"RSS delta: {round(r.rss_end_mb - r.rss_start_mb, 2)} MB over {iterations} calls"
    results.append(r)

    # Sustained projection calls with growing calendar
    def sustained_projection():
        state = build_twin_state({"athlete_id": f"mem-{rng.randrange(9999)}"})
        plan = []
        base = datetime(2026, 6, 12)
        for d in range(rng.randint(30, 120)):
            plan.append({"date": (base + timedelta(days=d)).strftime("%Y-%m-%d"),
                         "training_load": rng.uniform(30, 120), "duration_min": rng.randint(45, 120)})
        project_season_from_plan(state, plan, max_days=180)

    r2 = _bench("memory_sustained_projection", sustained_projection, iterations)
    r2.notes = f"RSS delta: {round(r2.rss_end_mb - r2.rss_start_mb, 2)} MB over {iterations} calls"
    results.append(r2)

    # Large power array processing — simulates 5-hour ride at 1 Hz
    def large_power_array():
        from engines.io.fit_parser import parse_fit_records_enhanced
        n = 18000  # 5 hours
        base_dt = datetime(2026, 1, 1, 8, 0, 0)
        records = [{"timestamp": base_dt + timedelta(seconds=i),
                     "power": int(max(0, 200 + 40 * math.sin(i / 100) + rng.gauss(0, 20))),
                     "heart_rate": int(140 + 15 * math.sin(i / 300))}
                   for i in range(n)]
        stream = parse_fit_records_enhanced(records, session_dict={"sport": "cycling", "start_time": base_dt})
        build_workout_summary(stream, weight_kg=75.0, ftp=260)

    r3 = _bench("memory_5h_ride_summary", large_power_array, max(5, iterations // 5))
    r3.notes = f"RSS delta: {round(r3.rss_end_mb - r3.rss_start_mb, 2)} MB over {r3.iterations} calls"
    results.append(r3)

    return results


# ---------------------------------------------------------------------------
# 3. SYNTHETIC FIT BINARY GENERATOR + UPLOAD PATH
# ---------------------------------------------------------------------------

def _build_minimal_fit_binary(power_series: List[int], *, sport: str = "cycling") -> bytes:
    """Build a minimal but valid FIT binary that fitparse can read.

    This is NOT a full SDK-grade encoder. It creates the minimum viable file
    structure: file_header + data messages (file_id + records) + CRC. It's
    enough for parse_fit_file_enhanced to extract power/timestamp arrays,
    which is what we need to stress the real upload→parse→engine path.
    """
    # FIT protocol constants
    MESG_FILE_ID = 0
    MESG_RECORD = 20
    FIELD_TYPE = 0        # file_id.type
    FIELD_TIMESTAMP = 253 # record.timestamp
    FIELD_POWER = 7       # record.power

    buf = io.BytesIO()

    # We'll write raw bytes that fitparse's low-level reader can handle.
    # Strategy: use the "compressed timestamp" format which is simpler.
    # Actually, the simplest approach: write a proper FIT file using struct.

    # -- File header (14 bytes, FIT 2.0) --
    header_size = 14
    protocol_version = 0x20  # 2.0
    profile_version = 2132   # 21.32
    data_size_placeholder = 0  # fill later
    data_type = b".FIT"
    crc_header = 0x0000

    buf.write(struct.pack("<BBHLBBBB",
        header_size, protocol_version,
        profile_version, data_size_placeholder,
        data_type[0], data_type[1], data_type[2], data_type[3],
    ))
    buf.write(struct.pack("<H", crc_header))
    # Total header: 12 + 2 = 14 bytes

    data_start = buf.tell()

    # -- Definition message for file_id (mesg 0) --
    # Record header: 0x40 = definition, local message 0
    buf.write(struct.pack("B", 0x40))
    buf.write(struct.pack("B", 0))       # reserved
    buf.write(struct.pack("B", 0))       # architecture: little-endian
    buf.write(struct.pack("<H", MESG_FILE_ID))  # global mesg num
    buf.write(struct.pack("B", 1))       # num fields
    # Field: type (field_def_num=0, size=1, base_type=0 = enum)
    buf.write(struct.pack("BBB", FIELD_TYPE, 1, 0))

    # -- Data message for file_id --
    buf.write(struct.pack("B", 0x00))    # data, local message 0
    buf.write(struct.pack("B", 4))       # type = activity

    # -- Definition message for record (mesg 20) --
    buf.write(struct.pack("B", 0x41))    # definition, local message 1
    buf.write(struct.pack("B", 0))       # reserved
    buf.write(struct.pack("B", 0))       # little-endian
    buf.write(struct.pack("<H", MESG_RECORD))
    buf.write(struct.pack("B", 2))       # 2 fields
    # Field: timestamp (253, 4 bytes, uint32)
    buf.write(struct.pack("BBB", FIELD_TIMESTAMP, 4, 134))  # 134 = uint32
    # Field: power (7, 2 bytes, uint16)
    buf.write(struct.pack("BBB", FIELD_POWER, 2, 132))      # 132 = uint16

    # -- Data messages for each power sample --
    base_ts = 1000000000  # FIT epoch offset
    for i, pw in enumerate(power_series):
        buf.write(struct.pack("B", 0x01))  # data, local message 1
        buf.write(struct.pack("<I", base_ts + i))
        buf.write(struct.pack("<H", max(0, min(65534, int(pw)))))

    data_end = buf.tell()
    data_size = data_end - data_start

    # -- CRC16 of the data section --
    buf.write(struct.pack("<H", 0x0000))  # placeholder CRC

    # -- Patch data_size in header --
    buf.seek(4)
    buf.write(struct.pack("<L", data_size))

    return buf.getvalue()


async def run_fit_upload_bench(base_url: str, iterations: int = 15, seed: int = 42) -> List[BenchResult]:
    """Upload real FIT binaries through the HTTP endpoint and measure full path."""
    import httpx
    rng = random.Random(seed)
    results: List[BenchResult] = []

    async def upload_one(client: httpx.AsyncClient, n_samples: int) -> Tuple[int, float]:
        power = [int(max(0, 200 + 40 * math.sin(i / 80) + rng.gauss(0, 15))) for i in range(n_samples)]
        fit_bytes = _build_minimal_fit_binary(power)
        t0 = time.perf_counter()
        resp = await client.post(
            "/ride/summary",
            files={"file": ("stress.fit", fit_bytes, "application/octet-stream")},
            data={"weight_kg": "75", "gender": "MALE", "training_years": "10",
                  "discipline": "ENDURANCE", "ftp": "260", "hrv_max_windows": "100"},
            timeout=60.0,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return resp.status_code, elapsed_ms

    for label, n_samples in [("fit_1800s_30min", 1800), ("fit_3600s_1h", 3600), ("fit_7200s_2h", 7200)]:
        timings: List[float] = []
        errors = 0
        async with httpx.AsyncClient(base_url=base_url.rstrip("/")) as client:
            for _ in range(iterations):
                try:
                    status, ms = await upload_one(client, n_samples)
                    timings.append(ms)
                    if status >= 500:
                        errors += 1
                except Exception:
                    errors += 1
                    timings.append(0.0)
        if timings:
            results.append(BenchResult(
                name=label,
                iterations=iterations,
                total_s=round(sum(timings) / 1000, 3),
                mean_ms=round(sum(timings) / len(timings), 2),
                p50_ms=round(_percentile(timings, 0.5), 2),
                p95_ms=round(_percentile(timings, 0.95), 2),
                p99_ms=round(_percentile(timings, 0.99), 2),
                max_ms=round(max(timings), 2),
                min_ms=round(min(timings), 2),
                errors=errors,
                notes=f"{n_samples}s FIT binary, full upload→parse→summary path",
            ))
    return results


# ---------------------------------------------------------------------------
# 4. CONCURRENT TWIN_STATE CONTENTION (same athlete, multiple workers)
# ---------------------------------------------------------------------------

async def run_contention_bench(base_url: str, concurrency: int = 8, requests_per_worker: int = 15, seed: int = 42) -> List[BenchResult]:
    """N workers all updating the same athlete's twin_state simultaneously.

    This finds race conditions, lost updates, or serialization errors in the
    stateless API contract: since the backend is stateless, the CALLER is
    responsible for sequencing. But the backend must not crash or corrupt its
    own intermediate computations when called concurrently for the same ID.
    """
    import httpx
    rng = random.Random(seed)
    ATHLETE_ID = "contention-athlete-0001"

    base_state = {
        "schema_version": "twin_state.v1",
        "athlete_id": ATHLETE_ID,
        "created_at": _now(), "updated_at": _now(),
        "athlete_profile": {"athlete_id": ATHLETE_ID, "weight_kg": 75, "gender": "MALE", "training_years": 10},
        "measured_anchor": {}, "metabolic_snapshot": {"status": "success", "mlss_power_watts": 250},
        "metabolic_metrics": {"cp_w": 270, "w_prime_j": 20000, "vo2max_ml_kg_min": 55, "vlamax_mmol_l_s": 0.45},
        "rolling_power_curve": {"5": 750, "60": 400, "300": 310, "1200": 270, "3600": 240},
        "load_state": {"ctl": 65, "atl": 70, "tsb": -5},
        "readiness_state": {}, "sensor_quality": {}, "power_source_state": {},
        "workout_calendar_state": {}, "last_compliance_results": [],
        "team_calibration_state": {}, "state_confidence": {"overall": 0.7},
        "scope_declarations": {}, "warnings": [],
        "event_log": [{"type": "contention_test_start", "at": _now()}],
    }

    timings: List[float] = []
    errors = 0
    status_codes: Dict[int, int] = {}

    async def worker(wid: int, client: httpx.AsyncClient):
        nonlocal errors
        for _ in range(requests_per_worker):
            # Alternate between projection and twin-state-update
            if rng.random() < 0.5:
                plan = [{"date": f"2026-07-{d:02d}", "training_load": rng.uniform(40, 100)}
                        for d in range(1, rng.randint(8, 30))]
                payload = {"twin_state": base_state, "calendar_plan": plan, "max_days": 60}
                path = "/twin/state/project"
            else:
                payload = {"twin_state": base_state, "ride_summary": {"tss": rng.uniform(40, 120)},
                           "ingest_result": {"curve": {"300": 300 + rng.gauss(0, 15)}}}
                path = "/twin/state/update-from-ride"
            t0 = time.perf_counter()
            try:
                resp = await client.post(path, json=payload, timeout=30.0)
                elapsed = (time.perf_counter() - t0) * 1000.0
                timings.append(elapsed)
                status_codes[resp.status_code] = status_codes.get(resp.status_code, 0) + 1
                if resp.status_code >= 500:
                    errors += 1
            except Exception:
                errors += 1
                timings.append((time.perf_counter() - t0) * 1000.0)

    async with httpx.AsyncClient(base_url=base_url.rstrip("/")) as client:
        await asyncio.gather(*[worker(i, client) for i in range(concurrency)])

    total = len(timings)
    return [BenchResult(
        name=f"contention_{concurrency}workers_same_athlete",
        iterations=total,
        total_s=round(sum(timings) / 1000, 3),
        mean_ms=round(sum(timings) / total, 2) if total else 0,
        p50_ms=round(_percentile(timings, 0.5), 2),
        p95_ms=round(_percentile(timings, 0.95), 2),
        p99_ms=round(_percentile(timings, 0.99), 2),
        max_ms=round(max(timings), 2) if timings else 0,
        min_ms=round(min(timings), 2) if timings else 0,
        errors=errors,
        notes=f"status_codes={json.dumps(status_codes)}; {concurrency} workers × {requests_per_worker} reqs on SAME athlete_id",
    )]


# ---------------------------------------------------------------------------
# 5. PATHOLOGICAL INPUT FUZZER
# ---------------------------------------------------------------------------

def run_pathological_bench(iterations: int = 10, seed: int = 42) -> List[BenchResult]:
    """Feed worst-case inputs to engines and measure behaviour.

    These are not random garbage — they're physiologically plausible edge cases
    that stress solver convergence, numerical stability, and bounds checking.
    """
    from engines.metabolic.metabolic_profiler import MetabolicProfiler
    from engines.core.athlete_context import AthleteContext
    from engines.projection.season_projection_engine import project_season_from_plan
    from engines.twin_state.models import build_twin_state
    rng = random.Random(seed)
    results: List[BenchResult] = []

    # A: Flat MMP (all durations same power — solver has no curvature to fit)
    flat_mmp = {str(d): 250.0 for d in [1, 5, 15, 60, 300, 1200, 3600]}
    ctx_flat = AthleteContext(gender="MALE", training_years=10, discipline="ENDURANCE")
    profiler_flat = MetabolicProfiler(75.0, ctx_flat)
    results.append(_bench(
        "pathological_flat_mmp",
        lambda: profiler_flat.generate_metabolic_snapshot(flat_mmp),
        iterations,
    ))

    # B: Inverted MMP (longer durations have HIGHER power — physiologically impossible)
    inv_mmp = {"1": 200.0, "5": 220.0, "15": 250.0, "60": 300.0, "300": 350.0, "1200": 380.0, "3600": 400.0}
    profiler_inv = MetabolicProfiler(75.0, ctx_flat)
    results.append(_bench(
        "pathological_inverted_mmp",
        lambda: profiler_inv.generate_metabolic_snapshot(inv_mmp),
        iterations,
    ))

    # C: Single-point MMP (minimum info — can the solver even produce output?)
    single_mmp = {"300": 280.0}
    profiler_single = MetabolicProfiler(75.0, ctx_flat)
    results.append(_bench(
        "pathological_single_point_mmp",
        lambda: profiler_single.generate_metabolic_snapshot(single_mmp),
        iterations,
    ))

    # D: Extreme values (superhuman 2400W sprint + 50W long — maximum dynamic range)
    extreme_mmp = {"1": 2400.0, "5": 1800.0, "15": 900.0, "60": 550.0, "300": 350.0, "1200": 250.0, "3600": 200.0}
    ctx_heavy = AthleteContext(gender="MALE", training_years=5, discipline="SPRINT")
    profiler_extreme = MetabolicProfiler(110.0, ctx_heavy)
    results.append(_bench(
        "pathological_extreme_range",
        lambda: profiler_extreme.generate_metabolic_snapshot(extreme_mmp),
        iterations,
    ))

    # E: Near-zero power (metabolically degenerate — can trigger division issues)
    tiny_mmp = {"1": 45.0, "5": 38.0, "15": 30.0, "60": 22.0, "300": 18.0, "1200": 15.0, "3600": 12.0}
    ctx_tiny = AthleteContext(gender="FEMALE", training_years=1, discipline="ENDURANCE")
    profiler_tiny = MetabolicProfiler(45.0, ctx_tiny)
    results.append(_bench(
        "pathological_near_zero_power",
        lambda: profiler_tiny.generate_metabolic_snapshot(tiny_mmp),
        iterations,
    ))

    # F: Max-length calendar projection (hit MAX_PROJECTION_DAYS boundary)
    def big_projection():
        state = build_twin_state({"athlete_id": "pathological-proj"})
        plan = [{"date": (datetime(2026, 6, 12) + timedelta(days=d)).strftime("%Y-%m-%d"),
                 "training_load": rng.uniform(20, 150), "duration_min": rng.randint(30, 180)}
                for d in range(400)]
        project_season_from_plan(state, plan, max_days=400)

    results.append(_bench("pathological_400day_projection", big_projection, iterations))

    return results


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def generate_report(all_results: Dict[str, List[BenchResult]], output_dir: Path) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    report: Dict[str, Any] = {
        "generated_at": _now(),
        "sections": {},
        "bottleneck_summary": [],
    }
    md_lines = ["# Deep Bottleneck Report", "", f"Generated: {_now()}", ""]

    for section_name, benchmarks in all_results.items():
        section_data = [b.to_dict() for b in benchmarks]
        report["sections"][section_name] = section_data

        md_lines.append(f"## {section_name}")
        md_lines.append("")
        md_lines.append("| Benchmark | Iters | Mean ms | p95 ms | Max ms | Errors | RSS Δ MB | Notes |")
        md_lines.append("|---|---:|---:|---:|---:|---:|---:|---|")
        for b in benchmarks:
            rss_delta = round(b.rss_end_mb - b.rss_start_mb, 2) if b.rss_start_mb else 0
            md_lines.append(
                f"| `{b.name}` | {b.iterations} | {b.mean_ms} | {b.p95_ms} | {b.max_ms} "
                f"| {b.errors} | {rss_delta} | {b.notes[:80]} |"
            )
        md_lines.append("")

        # Identify bottlenecks: anything with p95 > 2000ms or errors > 0 or RSS delta > 20MB
        for b in benchmarks:
            flags = []
            if b.p95_ms > 2000:
                flags.append(f"p95={b.p95_ms}ms (slow)")
            if b.errors > 0:
                flags.append(f"{b.errors} errors")
            rss_d = b.rss_end_mb - b.rss_start_mb
            if rss_d > 20:
                flags.append(f"RSS grew {rss_d:.1f}MB")
            if flags:
                report["bottleneck_summary"].append({"benchmark": b.name, "flags": flags})

    if report["bottleneck_summary"]:
        md_lines.append("## Bottleneck flags")
        md_lines.append("")
        for item in report["bottleneck_summary"]:
            md_lines.append(f"- **{item['benchmark']}**: {', '.join(item['flags'])}")
        md_lines.append("")
    else:
        md_lines.append("## No bottleneck flags triggered.")
        md_lines.append("")

    md_lines.extend([
        "## What this covers that the HTTP stress test does not",
        "",
        "- **Profiler isolation**: scipy.least_squares solver timings per MMP shape, separated from HTTP overhead.",
        "- **Memory tracking**: RSS watermark over sustained calls; catches numpy/scipy allocation leaks.",
        "- **Real FIT binary path**: actual .fit upload → tempfile → fitparse → engine, not just power_json shortcut.",
        "- **Same-athlete contention**: N workers hitting identical athlete_id concurrently to surface race conditions.",
        "- **Pathological inputs**: flat/inverted/single-point/extreme/near-zero MMP; max-length projections.",
    ])

    (output_dir / "deep_bottleneck_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (output_dir / "deep_bottleneck_report.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Deep bottleneck finder")
    p.add_argument("--mode", choices=["all", "profiler", "memory", "fit-upload", "contention", "pathological"],
                   default="all")
    p.add_argument("--base-url", default=os.getenv("STRESS_BASE_URL", "http://127.0.0.1:8000"))
    p.add_argument("--iterations", type=int, default=15)
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--output-dir", type=Path, default=Path("stress_outputs/deep"))
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    all_results: Dict[str, List[BenchResult]] = {}
    modes = (["profiler", "memory", "fit-upload", "contention", "pathological"]
             if args.mode == "all" else [args.mode])

    for mode in modes:
        print(f"\n{'='*60}\n  Running: {mode}\n{'='*60}", flush=True)
        try:
            if mode == "profiler":
                all_results["profiler"] = run_profiler_bench(args.iterations, args.seed)
            elif mode == "memory":
                all_results["memory"] = run_memory_bench(args.iterations, args.seed)
            elif mode == "fit-upload":
                all_results["fit_upload"] = asyncio.run(
                    run_fit_upload_bench(args.base_url, args.iterations, args.seed))
            elif mode == "contention":
                all_results["contention"] = asyncio.run(
                    run_contention_bench(args.base_url, args.concurrency, args.iterations, args.seed))
            elif mode == "pathological":
                all_results["pathological"] = run_pathological_bench(args.iterations, args.seed)
        except Exception as exc:
            print(f"  FAILED: {exc}", flush=True)
            traceback.print_exc()
            all_results[mode] = [BenchResult(
                name=f"{mode}_FAILED", iterations=0, total_s=0, mean_ms=0,
                p50_ms=0, p95_ms=0, p99_ms=0, max_ms=0, min_ms=0,
                errors=1, notes=f"{type(exc).__name__}: {exc}",
            )]

    report = generate_report(all_results, args.output_dir)
    print(f"\nReport written to {args.output_dir}/", flush=True)
    if report["bottleneck_summary"]:
        print("\nBottleneck flags:")
        for item in report["bottleneck_summary"]:
            print(f"  - {item['benchmark']}: {', '.join(item['flags'])}")
    else:
        print("\nNo bottleneck flags triggered.")
    return 1 if report["bottleneck_summary"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
