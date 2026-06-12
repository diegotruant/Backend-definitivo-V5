# Multi-tenant stress testing — Backend-definitivo-V5.1

This backend is stateless at the HTTP/engine layer. That is good for scaling,
but it does not remove the need for load testing. The first production gate is
not another feature; it is a repeatable stress harness that attacks the public
API like a SaaS product with many tenants, coaches and athletes.

## Tool

```bash
python tools/stress/multitenant_stress.py \
  --base-url http://127.0.0.1:8000 \
  --profile balanced \
  --duration-s 60 \
  --concurrency 32 \
  --tenant-count 20 \
  --coach-count 250 \
  --athlete-count 100000 \
  --output-dir stress_outputs/balanced
```

The simulator calls a weighted mix of endpoints:

- `/health`
- `/load/manual`
- `/profile/snapshot`
- `/twin/state/build`
- `/projection/season`
- `/workouts/feasibility`
- `/power-source/normalize`
- `/ride/summary` with `power_json`
- `/performance/neuromuscular-profile` with `power_json`

It records one row per request and produces:

- `stress_summary.json`
- `stress_requests.csv`
- `stress_report.md`

## Profiles

- `balanced`: general SaaS traffic mix.
- `read-heavy`: many lightweight state/read-model calls.
- `ingest-heavy`: more ride summary and neuromuscular analysis.
- `projection-heavy`: more season projection calls.
- `full`: balanced mix with heavier synthetic streams.

## Pass/fail gates

By default the run fails if:

- server errors/timeouts exceed 1%; or
- aggregate p95 latency exceeds 10 seconds.

These are local-development thresholds. Production SLOs should be stricter for
light endpoints and separated by endpoint class:

- health/manual/twin state: p95 < 250–500 ms
- projection/feasibility/snapshot: p95 < 1–3 s
- ride summary/neuromuscular/FIT ingest: async job or p95 < 10–30 s depending on file size

## What this test proves

It proves that the stateless API and analytics engines can survive concurrent,
cardinality-heavy request patterns without crashing, looping, returning 5xx, or
leaking invalid JSON.

## What this test does not prove

It does **not** test:

- database locks or migration safety;
- object storage throughput;
- queue backpressure;
- authentication provider rate limits;
- tenant-level authorization isolation;
- autoscaling behaviour;
- CDN/WAF/body-size behaviour;
- true million-athlete persistence.

Those require an infrastructure stress stage with the real DB, queue, storage,
worker pool and observability stack.

## Recommended production architecture

For multi-tenant SaaS scale, keep the API stateless but move heavy computations
behind job queues:

1. Upload FIT to object storage.
2. API creates `analysis_job` row and returns `202 Accepted`.
3. Worker pool runs parser/summary/projection.
4. Results are stored as versioned artifacts/TwinState snapshots.
5. Frontend polls job status or receives websocket/SSE notification.
6. Rate limits are enforced per tenant and per coach.

Do not let public HTTP workers parse hundreds of large FIT files synchronously
in production.
