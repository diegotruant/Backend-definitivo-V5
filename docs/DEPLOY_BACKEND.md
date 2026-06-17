# Deploy backend — Digital Twin API V5.1

Minimal production deployment guide for `uvicorn api_app:app`.

## Requirements

- Python **3.10+** (CI uses 3.11)
- `pip install -r requirements-dev.txt` (or split prod deps if you extract later)
- Outbound network only if engines call external services (default: none)

## Quick start (single host)

```bash
git clone <repo> && cd Backend-definitivo-V5
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
# Edit .env — see Environment variables below
uvicorn api_app:app --host 0.0.0.0 --port 8000
```

Verify:

```bash
curl -s http://localhost:8000/health
curl -s http://localhost:8000/openapi.json | head
```

## Environment variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `DIGITAL_TWIN_CORS_ORIGINS` | For browser clients | empty | Comma-separated origins, e.g. `https://app.vercel.app` |
| `DIGITAL_TWIN_API_TITLE` | No | Digital Twin Fisiologico API | OpenAPI title |
| `DIGITAL_TWIN_API_VERSION` | No | 5.1.1 | OpenAPI version string |
| `MAX_UPLOAD_BYTES` | No | 41943040 (40 MB) | Per-file upload cap |
| `MAX_UPLOAD_FILES` | No | 25 | Multi-file propose limit |
| `MAX_POWER_SAMPLES` | No | 200000 | Inline `power_json` cap |
| `MAX_JSON_DEPTH` | No | 64 | TwinState / calendar nesting |
| `MAX_PROJECTION_DAYS` | No | 400 | Season projection bound |
| `MAX_CALENDAR_EVENTS` | No | 1000 | Calendar plan bound |
| `DIGITAL_TWIN_RATE_LIMIT_ENABLED` | No | `true` | Enable in-memory rate limiting middleware |
| `DIGITAL_TWIN_RATE_LIMIT_MAX_REQUESTS` | No | `120` | Max requests per `(IP, method, path)` window |
| `DIGITAL_TWIN_RATE_LIMIT_WINDOW_S` | No | `60` | Sliding-window size in seconds |
| `DIGITAL_TWIN_REQUIRE_ATHLETE_ID` | No | `false` | Enforce `X-Athlete-Id` on athlete-scoped routes |

Copy from `.env.example` and set at least **CORS** when a frontend calls the API from the browser.

## Process manager (systemd example)

```ini
[Unit]
Description=Digital Twin API
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/digital-twin
EnvironmentFile=/opt/digital-twin/.env
ExecStart=/opt/digital-twin/.venv/bin/uvicorn api_app:app --host 127.0.0.1 --port 8000 --workers 2
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Put nginx or Caddy in front for TLS:

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_read_timeout 120s;
    client_max_body_size 45m;
}
```

FIT uploads and `/profile/snapshot` can be slow — use **≥120s** read timeout.

## Workers

- **CPU-bound** endpoints: `ride/summary`, `profile/snapshot`, FIT parse
- Start with **2 workers** on a 2-vCPU VM; scale horizontally if latency grows
- Stateless API — no sticky sessions required

## Health checks

| Endpoint | Expected |
|----------|----------|
| `GET /health` | `200`, `{"status":"ok",...}` |

Use for load balancer probes. Do not use `/docs` for probes (heavier).

## Security checklist

- [ ] TLS terminated at reverse proxy
- [ ] CORS allowlist set (not `*` in production unless intentional)
- [ ] Upload limits left at defaults or tuned for your FIT sizes
- [ ] Rate limiting configured for expected traffic profile
- [ ] Decide tenant policy: set `DIGITAL_TWIN_REQUIRE_ATHLETE_ID=true` when clients are ready
- [ ] No secrets in repo — env only
- [ ] Log aggregation for 5xx (FastAPI logs exceptions server-side)

## CI parity before deploy

On the release commit:

```bash
make check
```

Or trigger GitHub Actions **Full backend check** (`workflow_dispatch`).

## Docker (optional sketch)

Not shipped in repo — minimal pattern:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "api_app:app", "--host", "0.0.0.0", "--port", "8000"]
```

## Related

- `docs/FRONTEND_CONNECT_NEXT_VERCEL.md` — connect Vercel frontend
- `docs/TROUBLESHOOTING.md` — ops issues
- `Makefile` — `make run`, `make check`
