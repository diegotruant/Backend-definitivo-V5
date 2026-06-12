#!/usr/bin/env python3
"""Multi-tenant HTTP stress simulator for Backend-definitivo-V5.1.

This is intentionally dependency-light and product-shaped rather than a tiny
unit benchmark.  It stresses the public FastAPI contract with tenant/coach /
athlete cardinality, concurrent workers, realistic endpoint mix, bounded
request timeouts and explicit pass/fail gates.

It does NOT prove that one Python process can serve millions of athletes.  It
proves whether the stateless analytics API keeps latency/error budgets under a
specified synthetic workload.  For production capacity planning, run the same
script against a deployed cluster and increase --concurrency / --duration-s /
--requests until the SLO breaks.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import os
import random
from datetime import date, timedelta
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import httpx


EndpointName = str


@dataclass(slots=True)
class RequestResult:
    endpoint: EndpointName
    status_code: int
    ok: bool
    latency_ms: float
    bytes_out: int
    error: str = ""
    tenant_id: str = ""
    coach_id: str = ""
    athlete_id: str = ""


@dataclass(slots=True)
class WorkloadContext:
    rng: random.Random
    tenant_count: int
    coach_count: int
    athlete_count: int
    power_samples_min: int
    power_samples_max: int
    calendar_events_min: int
    calendar_events_max: int
    weight_kg: float = 70.0

    def identity(self) -> Tuple[str, str, str]:
        tenant_i = self.rng.randrange(max(1, self.tenant_count))
        coach_i = self.rng.randrange(max(1, self.coach_count))
        athlete_i = self.rng.randrange(max(1, self.athlete_count))
        return (
            f"tenant-{tenant_i:04d}",
            f"coach-{coach_i:05d}",
            f"athlete-{athlete_i:08d}",
        )


@dataclass(slots=True)
class WorkItem:
    name: EndpointName
    method: str
    path: str
    kwargs_factory: Callable[[WorkloadContext, str, str, str], Dict[str, Any]]
    weight: int
    timeout_s: float


def _json_size(payload: Any) -> int:
    try:
        return len(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    except Exception:
        return 0


def _power_series(ctx: WorkloadContext, *, heavy: bool = False) -> List[float]:
    n = ctx.rng.randint(ctx.power_samples_min, ctx.power_samples_max)
    if heavy:
        n = min(max(n * 2, 1800), 7200)
    base = ctx.rng.uniform(145, 235)
    series: List[float] = []
    sprint_every = ctx.rng.randint(180, 420)
    for i in range(n):
        noise = ctx.rng.gauss(0, 18)
        wave = 35.0 * math.sin(i / 95.0) + 12.0 * math.sin(i / 17.0)
        p = max(0.0, base + wave + noise)
        # Short sprint spikes, enough to exercise MMP/neuromuscular paths.
        if i % sprint_every in (0, 1, 2, 3, 4):
            p += ctx.rng.uniform(350, 650)
        # Coasting segments: zeros are valid power samples, not missing data.
        if i % 600 in range(40, 70):
            p = 0.0
        series.append(round(p, 1))
    return series


def _mmp_payload(ctx: WorkloadContext) -> Dict[str, float]:
    cp = ctx.rng.uniform(230, 320)
    return {
        "1": round(cp * ctx.rng.uniform(2.7, 3.4), 1),
        "5": round(cp * ctx.rng.uniform(2.2, 2.9), 1),
        "15": round(cp * ctx.rng.uniform(1.7, 2.1), 1),
        "60": round(cp * ctx.rng.uniform(1.35, 1.75), 1),
        "300": round(cp * ctx.rng.uniform(1.10, 1.28), 1),
        "1200": round(cp * ctx.rng.uniform(0.92, 1.04), 1),
        "3600": round(cp * ctx.rng.uniform(0.78, 0.92), 1),
    }


def _athlete(ctx: WorkloadContext, athlete_id: str) -> Dict[str, Any]:
    return {
        "athlete_id": athlete_id,
        "weight_kg": round(ctx.rng.uniform(55, 88), 1),
        "gender": ctx.rng.choice(["MALE", "FEMALE"]),
        "training_years": ctx.rng.randint(2, 18),
        "discipline": ctx.rng.choice(["ENDURANCE", "ROAD", "GRAVEL", "SPRINT"]),
    }


def _twin_state(ctx: WorkloadContext, tenant_id: str, coach_id: str, athlete_id: str) -> Dict[str, Any]:
    cp = ctx.rng.uniform(220, 330)
    now = "2026-06-12T08:00:00Z"
    return {
        "schema_version": "twin_state.v1",
        "athlete_id": athlete_id,
        "tenant_id": tenant_id,
        "coach_id": coach_id,
        "created_at": now,
        "updated_at": now,
        "athlete_profile": {
            "athlete_id": athlete_id,
            "weight_kg": round(ctx.rng.uniform(58, 84), 1),
            "gender": "MALE",
            "training_years": ctx.rng.randint(3, 16),
        },
        "measured_anchor": {},
        "metabolic_snapshot": {
            "status": "success",
            "mlss_power_watts": round(cp * 0.93, 1),
            "estimated_vo2max": round(ctx.rng.uniform(48, 68), 1),
            "estimated_vlamax_mmol_L_s": round(ctx.rng.uniform(0.25, 0.75), 3),
        },
        "metabolic_metrics": {
            "cp_w": round(cp, 1),
            "w_prime_j": round(ctx.rng.uniform(12000, 26000), 0),
            "vo2max_ml_kg_min": round(ctx.rng.uniform(48, 68), 1),
            "vlamax_mmol_l_s": round(ctx.rng.uniform(0.25, 0.75), 3),
        },
        "rolling_power_curve": {
            "5": round(cp * 2.65, 1),
            "60": round(cp * 1.55, 1),
            "300": round(cp * 1.18, 1),
            "1200": round(cp * 0.98, 1),
            "3600": round(cp * 0.86, 1),
        },
        "load_state": {
            "ctl": round(ctx.rng.uniform(35, 95), 1),
            "atl": round(ctx.rng.uniform(30, 115), 1),
            "tsb": round(ctx.rng.uniform(-35, 25), 1),
        },
        "readiness_state": {},
        "sensor_quality": {},
        "power_source_state": {},
        "workout_calendar_state": {},
        "last_compliance_results": [],
        "team_calibration_state": {},
        "state_confidence": {"overall": round(ctx.rng.uniform(0.45, 0.85), 2)},
        "scope_declarations": {
            "non_cycling_load": "manual_injection_supported_v1",
            "female_physiology": "optional_modifier_supported_v1_not_mechanistic_cycle_model",
        },
        "warnings": [],
        "event_log": [{"type": "stress_state_created", "at": now}],
    }


def _calendar_plan(ctx: WorkloadContext) -> List[Dict[str, Any]]:
    n = ctx.rng.randint(ctx.calendar_events_min, ctx.calendar_events_max)
    plan: List[Dict[str, Any]] = []
    base_day = date(2026, 6, 12)
    for i in range(n):
        day = 1 + i
        kind = ctx.rng.choice(["endurance", "tempo", "vo2", "recovery", "sprint"])
        load = {
            "recovery": ctx.rng.uniform(15, 35),
            "endurance": ctx.rng.uniform(45, 85),
            "tempo": ctx.rng.uniform(70, 115),
            "vo2": ctx.rng.uniform(90, 135),
            "sprint": ctx.rng.uniform(60, 105),
        }[kind]
        plan.append({
            "assignment_id": f"planned-{i:04d}",
            "date": (base_day + timedelta(days=day)).isoformat(),
            "date_offset_days": day,
            "type": kind,
            "planned_load": round(load, 1),
            "duration_min": int(ctx.rng.choice([45, 60, 75, 90, 120])),
        })
    return plan


def _workout(ctx: WorkloadContext) -> Dict[str, Any]:
    cp_pct = ctx.rng.choice([0.65, 0.75, 0.88, 1.05, 1.18])
    reps = ctx.rng.randint(3, 8)
    steps = [
        {"duration_s": 600, "target_type": "power", "target": {"mode": "percent_cp", "value": 0.55}},
    ]
    for rep in range(reps):
        steps.append({"duration_s": ctx.rng.choice([60, 120, 180, 300]), "target_type": "power", "target": {"mode": "percent_cp", "value": cp_pct}})
        steps.append({"duration_s": ctx.rng.choice([60, 120, 180]), "target_type": "power", "target": {"mode": "percent_cp", "value": 0.45}})
    steps.append({"duration_s": 600, "target_type": "power", "target": {"mode": "percent_cp", "value": 0.50}})
    return {
        "workout_id": f"wo-{ctx.rng.randrange(1_000_000):06d}",
        "name": "stress generated workout",
        "sport": "cycling",
        "steps": steps,
    }


def build_workload(profile: str) -> List[WorkItem]:
    def json_post(payload: Any) -> Dict[str, Any]:
        return {"json": payload}

    def health(ctx: WorkloadContext, t: str, c: str, a: str) -> Dict[str, Any]:
        return {}

    def manual_load(ctx: WorkloadContext, t: str, c: str, a: str) -> Dict[str, Any]:
        return json_post({
            "duration_min": round(ctx.rng.uniform(20, 150), 1),
            "rpe": round(ctx.rng.uniform(2, 9), 1),
            "modality": ctx.rng.choice(["strength", "run", "mobility", "other"]),
            "muscle_damage_factor": round(ctx.rng.uniform(0.7, 1.6), 2),
            "notes": f"tenant={t};coach={c};athlete={a}",
        })

    def snapshot(ctx: WorkloadContext, t: str, c: str, a: str) -> Dict[str, Any]:
        return json_post({"mmp": _mmp_payload(ctx), "athlete": _athlete(ctx, a)})

    def twin_build(ctx: WorkloadContext, t: str, c: str, a: str) -> Dict[str, Any]:
        return json_post({"payload": _twin_state(ctx, t, c, a)})

    def projection(ctx: WorkloadContext, t: str, c: str, a: str) -> Dict[str, Any]:
        return json_post({
            "twin_state": _twin_state(ctx, t, c, a),
            "calendar_plan": _calendar_plan(ctx),
            "max_days": ctx.rng.randint(28, 180),
        })

    def feasibility(ctx: WorkloadContext, t: str, c: str, a: str) -> Dict[str, Any]:
        cp = ctx.rng.uniform(230, 320)
        return json_post({
            "workout": _workout(ctx),
            "athlete_profile": {
                "athlete_id": a,
                "cp_w": round(cp, 1),
                "critical_power_w": round(cp, 1),
                "w_prime_j": round(ctx.rng.uniform(12000, 26000), 0),
                "weight_kg": round(ctx.rng.uniform(58, 84), 1),
            },
            "context": {"tenant_id": t, "coach_id": c},
        })

    def power_normalize(ctx: WorkloadContext, t: str, c: str, a: str) -> Dict[str, Any]:
        activities = []
        baseline = ctx.rng.choice(["outdoor_pm", "smart_trainer"])
        for i in range(ctx.rng.randint(8, 24)):
            source = ctx.rng.choice(["outdoor_pm", "smart_trainer", "pedal_pm", "spider_pm"])
            offset = {"outdoor_pm": 1.0, "smart_trainer": 0.96, "pedal_pm": 1.02, "spider_pm": 0.99}[source]
            cp = ctx.rng.uniform(230, 310) * offset
            activities.append({
                "activity_id": f"{a}-act-{i:03d}",
                "source_id": source,
                "indoor": source == "smart_trainer",
                "mean_power_w": round(cp * ctx.rng.uniform(0.62, 0.88), 1),
                "normalized_power_w": round(cp * ctx.rng.uniform(0.75, 1.02), 1),
                "mmp": {"300": round(cp * 1.16, 1), "1200": round(cp * 0.98, 1)},
            })
        return json_post({"activities": activities, "baseline_source_id": baseline})

    def ride_summary(ctx: WorkloadContext, t: str, c: str, a: str) -> Dict[str, Any]:
        power = _power_series(ctx, heavy=profile in {"ingest-heavy", "full"})
        return {
            "data": {
                "weight_kg": str(ctx.weight_kg),
                "gender": "MALE",
                "training_years": "10",
                "discipline": "ENDURANCE",
                "ftp": str(ctx.rng.randint(230, 310)),
                "hrv_max_windows": "200",
                "power_json": json.dumps(power),
            }
        }

    def neuro(ctx: WorkloadContext, t: str, c: str, a: str) -> Dict[str, Any]:
        power = _power_series(ctx, heavy=False)
        return {
            "data": {
                "weight_kg": str(ctx.weight_kg),
                "sprint_threshold_w": str(ctx.rng.randint(550, 750)),
                "power_json": json.dumps(power),
            }
        }

    base: List[WorkItem] = [
        WorkItem("health", "GET", "/health", health, 5, 5.0),
        WorkItem("manual_load", "POST", "/load/manual", manual_load, 10, 10.0),
        WorkItem("profile_snapshot", "POST", "/profile/snapshot", snapshot, 15, 20.0),
        WorkItem("twin_state_build", "POST", "/twin/state/build", twin_build, 10, 15.0),
        WorkItem("season_projection", "POST", "/projection/season", projection, 10, 30.0),
        WorkItem("workout_feasibility", "POST", "/workouts/feasibility", feasibility, 15, 20.0),
        WorkItem("power_source_normalize", "POST", "/power-source/normalize", power_normalize, 10, 20.0),
        WorkItem("ride_summary_power_json", "POST", "/ride/summary", ride_summary, 15, 60.0),
        WorkItem("neuromuscular_profile", "POST", "/performance/neuromuscular-profile", neuro, 10, 30.0),
    ]
    if profile == "read-heavy":
        for item in base:
            if item.name in {"health", "twin_state_build", "manual_load"}:
                item.weight *= 2
            if item.name in {"ride_summary_power_json", "neuromuscular_profile"}:
                item.weight = max(2, item.weight // 2)
    elif profile == "ingest-heavy":
        for item in base:
            if item.name in {"ride_summary_power_json", "neuromuscular_profile"}:
                item.weight *= 3
            if item.name in {"health", "manual_load"}:
                item.weight = max(1, item.weight // 2)
    elif profile == "projection-heavy":
        for item in base:
            if item.name == "season_projection":
                item.weight *= 4
            if item.name == "ride_summary_power_json":
                item.weight = max(2, item.weight // 2)
    return base


def weighted_choice(rng: random.Random, items: List[WorkItem]) -> WorkItem:
    total = sum(max(0, i.weight) for i in items)
    pick = rng.uniform(0, total)
    upto = 0.0
    for item in items:
        upto += max(0, item.weight)
        if upto >= pick:
            return item
    return items[-1]


async def worker(
    worker_id: int,
    client: httpx.AsyncClient,
    ctx: WorkloadContext,
    items: List[WorkItem],
    deadline: float,
    request_budget: Optional[int],
    counter: "AtomicCounter",
    results: List[RequestResult],
    progress_every: int,
) -> None:
    while time.perf_counter() < deadline:
        if request_budget is not None and counter.value >= request_budget:
            return
        idx = await counter.next()
        if request_budget is not None and idx > request_budget:
            return
        tenant_id, coach_id, athlete_id = ctx.identity()
        item = weighted_choice(ctx.rng, items)
        kwargs = item.kwargs_factory(ctx, tenant_id, coach_id, athlete_id)
        started = time.perf_counter()
        status_code = 0
        ok = False
        err = ""
        bytes_out = 0
        try:
            timeout = httpx.Timeout(item.timeout_s)
            response = await client.request(item.method, item.path, timeout=timeout, **kwargs)
            status_code = response.status_code
            ok = 200 <= status_code < 500  # 4xx is valid rejection, not server crash.
            if status_code >= 500:
                err = response.text[:300]
            bytes_out = len(response.content or b"")
        except Exception as exc:  # noqa: BLE001 - capture benchmark failures
            err = f"{type(exc).__name__}: {exc}"
        latency_ms = (time.perf_counter() - started) * 1000.0
        results.append(RequestResult(
            endpoint=item.name,
            status_code=status_code,
            ok=ok,
            latency_ms=latency_ms,
            bytes_out=bytes_out,
            error=err,
            tenant_id=tenant_id,
            coach_id=coach_id,
            athlete_id=athlete_id,
        ))
        if progress_every and idx % progress_every == 0:
            print(f"progress requests={idx} worker={worker_id} last={item.name} status={status_code} latency_ms={latency_ms:.1f}", flush=True)


class AtomicCounter:
    def __init__(self) -> None:
        self.value = 0
        self._lock = asyncio.Lock()

    async def next(self) -> int:
        async with self._lock:
            self.value += 1
            return self.value


def percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * p
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (rank - lo)


def summarise(results: List[RequestResult], elapsed_s: float, args: argparse.Namespace) -> Dict[str, Any]:
    latencies = [r.latency_ms for r in results]
    total = len(results)
    failures = [r for r in results if not r.ok]
    server_errors = [r for r in results if r.status_code >= 500 or r.status_code == 0]
    by_endpoint: Dict[str, Dict[str, Any]] = {}
    for endpoint in sorted({r.endpoint for r in results}):
        rows = [r for r in results if r.endpoint == endpoint]
        lats = [r.latency_ms for r in rows]
        by_endpoint[endpoint] = {
            "requests": len(rows),
            "ok": sum(1 for r in rows if r.ok),
            "errors": sum(1 for r in rows if not r.ok),
            "server_errors_or_timeouts": sum(1 for r in rows if r.status_code >= 500 or r.status_code == 0),
            "status_codes": {str(code): sum(1 for r in rows if r.status_code == code) for code in sorted({r.status_code for r in rows})},
            "latency_ms": {
                "avg": round(statistics.fmean(lats), 2) if lats else 0.0,
                "p50": round(percentile(lats, 0.50), 2),
                "p95": round(percentile(lats, 0.95), 2),
                "p99": round(percentile(lats, 0.99), 2),
                "max": round(max(lats), 2) if lats else 0.0,
            },
        }
    error_rate = (len(server_errors) / total) if total else 1.0
    p95 = percentile(latencies, 0.95)
    pass_slo = (
        total > 0
        and error_rate <= args.max_error_rate
        and p95 <= args.max_p95_ms
    )
    return {
        "status": "pass" if pass_slo else "fail",
        "started_at_epoch_s": args.started_at,
        "elapsed_s": round(elapsed_s, 3),
        "base_url": args.base_url,
        "profile": args.profile,
        "config": {
            "duration_s": args.duration_s,
            "requests": args.requests,
            "concurrency": args.concurrency,
            "tenant_count": args.tenant_count,
            "coach_count": args.coach_count,
            "athlete_count": args.athlete_count,
            "power_samples_min": args.power_samples_min,
            "power_samples_max": args.power_samples_max,
            "calendar_events_min": args.calendar_events_min,
            "calendar_events_max": args.calendar_events_max,
            "max_error_rate": args.max_error_rate,
            "max_p95_ms": args.max_p95_ms,
        },
        "aggregate": {
            "requests": total,
            "ok": sum(1 for r in results if r.ok),
            "errors": len(failures),
            "server_errors_or_timeouts": len(server_errors),
            "server_error_rate": round(error_rate, 6),
            "throughput_rps": round(total / elapsed_s, 3) if elapsed_s > 0 else 0.0,
            "latency_ms": {
                "avg": round(statistics.fmean(latencies), 2) if latencies else 0.0,
                "p50": round(percentile(latencies, 0.50), 2),
                "p95": round(p95, 2),
                "p99": round(percentile(latencies, 0.99), 2),
                "max": round(max(latencies), 2) if latencies else 0.0,
            },
        },
        "by_endpoint": by_endpoint,
        "sample_errors": [
            {
                "endpoint": r.endpoint,
                "status_code": r.status_code,
                "latency_ms": round(r.latency_ms, 2),
                "error": r.error,
            }
            for r in server_errors[:20]
        ],
        "interpretation": {
            "what_this_tests": "HTTP API stateless analytics under concurrent multi-tenant synthetic workload.",
            "what_this_does_not_test": "Database locks, queue backpressure, object storage, auth provider, CDN/WAF, or million-athlete persistence; those require deployed infrastructure.",
        },
    }


async def run(args: argparse.Namespace) -> Tuple[Dict[str, Any], List[RequestResult]]:
    rng = random.Random(args.seed)
    ctx = WorkloadContext(
        rng=rng,
        tenant_count=args.tenant_count,
        coach_count=args.coach_count,
        athlete_count=args.athlete_count,
        power_samples_min=args.power_samples_min,
        power_samples_max=args.power_samples_max,
        calendar_events_min=args.calendar_events_min,
        calendar_events_max=args.calendar_events_max,
    )
    items = build_workload(args.profile)
    limits = httpx.Limits(max_connections=args.concurrency * 2, max_keepalive_connections=args.concurrency)
    results: List[RequestResult] = []
    counter = AtomicCounter()
    args.started_at = time.time()
    deadline = time.perf_counter() + args.duration_s
    start = time.perf_counter()
    async with httpx.AsyncClient(base_url=args.base_url.rstrip("/"), limits=limits) as client:
        # Warm-up health request makes connection errors clear before spawning workers.
        health = await client.get("/health", timeout=10.0)
        health.raise_for_status()
        tasks = [
            asyncio.create_task(worker(i, client, ctx, items, deadline, args.requests, counter, results, args.progress_every))
            for i in range(args.concurrency)
        ]
        await asyncio.gather(*tasks)
    elapsed_s = time.perf_counter() - start
    return summarise(results, elapsed_s, args), results


def write_outputs(summary: Dict[str, Any], results: List[RequestResult], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "stress_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    with (output_dir / "stress_requests.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["endpoint", "status_code", "ok", "latency_ms", "bytes_out", "tenant_id", "coach_id", "athlete_id", "error"],
        )
        writer.writeheader()
        for r in results:
            writer.writerow({
                "endpoint": r.endpoint,
                "status_code": r.status_code,
                "ok": r.ok,
                "latency_ms": round(r.latency_ms, 3),
                "bytes_out": r.bytes_out,
                "tenant_id": r.tenant_id,
                "coach_id": r.coach_id,
                "athlete_id": r.athlete_id,
                "error": r.error,
            })
    # Human-readable markdown for quick handoff.
    agg = summary["aggregate"]
    lines = [
        "# Multi-tenant stress report",
        "",
        f"Status: **{summary['status'].upper()}**",
        f"Profile: `{summary['profile']}`",
        f"Requests: {agg['requests']}",
        f"Throughput: {agg['throughput_rps']} req/s",
        f"Server errors/timeouts: {agg['server_errors_or_timeouts']} ({agg['server_error_rate'] * 100:.3f}%)",
        f"Latency p50/p95/p99/max: {agg['latency_ms']['p50']} / {agg['latency_ms']['p95']} / {agg['latency_ms']['p99']} / {agg['latency_ms']['max']} ms",
        "",
        "## Endpoint breakdown",
        "",
        "| Endpoint | Requests | Server errors/timeouts | p95 ms | p99 ms | Max ms |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for endpoint, row in summary["by_endpoint"].items():
        lat = row["latency_ms"]
        lines.append(f"| `{endpoint}` | {row['requests']} | {row['server_errors_or_timeouts']} | {lat['p95']} | {lat['p99']} | {lat['max']} |")
    lines.extend([
        "",
        "## Important limitation",
        "",
        "This is a stateless HTTP/API stress test. It does not cover DB contention, queue saturation, tenant auth, object storage or autoscaling. Use it as the first gate before infrastructure-level load tests.",
    ])
    (output_dir / "stress_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Multi-tenant stress simulator for Backend-definitivo-V5.1")
    parser.add_argument("--base-url", default=os.getenv("STRESS_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--profile", choices=["balanced", "read-heavy", "ingest-heavy", "projection-heavy", "full"], default="balanced")
    parser.add_argument("--duration-s", type=float, default=60.0)
    parser.add_argument("--requests", type=int, default=0, help="Total request budget. 0 means duration-based only.")
    parser.add_argument("--concurrency", type=int, default=32)
    parser.add_argument("--tenant-count", type=int, default=20)
    parser.add_argument("--coach-count", type=int, default=250)
    parser.add_argument("--athlete-count", type=int, default=100_000)
    parser.add_argument("--power-samples-min", type=int, default=600)
    parser.add_argument("--power-samples-max", type=int, default=2400)
    parser.add_argument("--calendar-events-min", type=int, default=14)
    parser.add_argument("--calendar-events-max", type=int, default=180)
    parser.add_argument("--seed", type=int, default=20260612)
    parser.add_argument("--max-error-rate", type=float, default=0.01)
    parser.add_argument("--max-p95-ms", type=float, default=10000.0)
    parser.add_argument("--output-dir", type=Path, default=Path("stress_outputs"))
    parser.add_argument("--progress-every", type=int, default=0)
    args = parser.parse_args(argv)
    if args.concurrency < 1:
        parser.error("--concurrency must be >= 1")
    if args.duration_s <= 0 and args.requests <= 0:
        parser.error("set positive --duration-s or --requests")
    if args.requests <= 0:
        args.requests = None
    return args


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    try:
        summary, results = asyncio.run(run(args))
    except Exception as exc:  # noqa: BLE001
        args.output_dir.mkdir(parents=True, exist_ok=True)
        failure = {
            "status": "fail",
            "error": f"{type(exc).__name__}: {exc}",
            "base_url": args.base_url,
            "profile": args.profile,
        }
        (args.output_dir / "stress_summary.json").write_text(json.dumps(failure, indent=2), encoding="utf-8")
        print(json.dumps(failure, indent=2), file=sys.stderr)
        return 2
    write_outputs(summary, results, args.output_dir)
    print(json.dumps(summary["aggregate"], indent=2), flush=True)
    return 0 if summary["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
