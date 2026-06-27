# Deploy backend — Digital Twin API V5.2

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
| `UVICORN_HOST` | No | `127.0.0.1` (dev) / `0.0.0.0` (Docker) | Uvicorn bind address |
| `UVICORN_PORT` | No | `8000` | Uvicorn listen port |
| `UVICORN_WORKERS` | No | `1` (dev) / `2` (Docker) | Uvicorn worker processes; see **Workers** |
| `DIGITAL_TWIN_CORS_ORIGINS` | For browser clients | empty | Comma-separated origins, e.g. `https://app.vercel.app` |
| `DIGITAL_TWIN_API_TITLE` | No | Digital Twin Fisiologico API | OpenAPI title |
| `DIGITAL_TWIN_API_VERSION` | No | 5.2.2 | OpenAPI version string |
| `MAX_UPLOAD_BYTES` | No | 41943040 (40 MB) | Per-file upload cap |
| `MAX_UPLOAD_FILES` | No | 25 | Multi-file propose limit |
| `MAX_GPX_BYTES` | No | 20971520 (20 MB) | GPX course string cap before XML parse |
| `MAX_POWER_SAMPLES` | No | 200000 | Inline `power_json` cap |
| `MAX_JSON_DEPTH` | No | 64 | TwinState / calendar nesting |
| `MAX_PROJECTION_DAYS` | No | 400 | Season projection bound |
| `MAX_CALENDAR_EVENTS` | No | 1000 | Calendar plan bound |
| `DIGITAL_TWIN_RATE_LIMIT_ENABLED` | No | `true` | Enable in-memory rate limiting middleware |
| `DIGITAL_TWIN_RATE_LIMIT_MAX_REQUESTS` | No | `120` | Max requests per `(IP, method, path)` window |
| `DIGITAL_TWIN_RATE_LIMIT_WINDOW_S` | No | `60` | Sliding-window size in seconds |
| `DIGITAL_TWIN_REQUIRE_ATHLETE_ID` | No | `false` | Enforce `X-Athlete-Id` on athlete-scoped routes |
| `DIGITAL_TWIN_AUTH_MODE` | No | `none` | `none`, `api_key`, or `jwt` |
| `DIGITAL_TWIN_API_KEY_AUTH_ENABLED` | No | `false` | Legacy flag; sets `api_key` mode when `AUTH_MODE` unset |
| `DIGITAL_TWIN_API_KEYS` | If api_key mode | empty | Comma-separated valid API keys |
| `DIGITAL_TWIN_API_KEY_ATHLETE_PREFIXES` | No | empty | Optional per-key athlete prefix allowlist (`key:prefix1|prefix2,...`) |
| `DIGITAL_TWIN_JWT_SECRET` | jwt + HS256 | empty | Shared secret for dev/staging JWT validation |
| `DIGITAL_TWIN_JWT_JWKS_URL` | jwt + RS256 | empty | OIDC JWKS URL (Auth0, Cognito, Keycloak, Supabase) |
| `DIGITAL_TWIN_JWT_AUDIENCE` | No | empty | Expected JWT `aud` claim |
| `DIGITAL_TWIN_JWT_ISSUER` | No | empty | Expected JWT `iss` claim |
| `DIGITAL_TWIN_JWT_ALGORITHMS` | No | `HS256` | Comma-separated allowed algorithms |

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
- **Rate limiting is per worker**: `_InMemoryRateLimiter` in `api/app.py` keeps counters in each process. With `--workers 2` and `DIGITAL_TWIN_RATE_LIMIT_MAX_REQUESTS=120`, a client can send roughly **240** requests per window before 429s (120 per worker), unless the load balancer pins traffic. Multiple API replicas multiply the ceiling further.
- **Strict global limits**: set `DIGITAL_TWIN_RATE_LIMIT_ENABLED=false` and enforce at nginx/Caddy/Cloudflare, or add a Redis-backed limiter later.

## Docker

Production image ships in the repository root:

```bash
docker build -t digital-twin-api .
docker run --rm -p 8000:8000 --env-file .env digital-twin-api
```

Defaults: `UVICORN_HOST=0.0.0.0`, `UVICORN_PORT=8000`, `UVICORN_WORKERS=2`, non-root user, `HEALTHCHECK` on `GET /health`. The image installs runtime dependencies only (`pip install .`); dev/test tools stay on the host CI image.

Override at run time:

```bash
docker run --rm -p 8000:8000 \
  -e DIGITAL_TWIN_CORS_ORIGINS=https://app.example.com \
  -e DIGITAL_TWIN_AUTH_MODE=jwt \
  -e DIGITAL_TWIN_JWT_JWKS_URL=https://issuer.example.com/.well-known/jwks.json \
  digital-twin-api
```

Put nginx or Caddy in front for TLS when exposing publicly.

## Health checks

| Endpoint | Expected |
|----------|----------|
| `GET /health` | `200`, `{"status":"ok",...}` |

Use for load balancer probes. Do not use `/docs` for probes (heavier).

## Security checklist

- [ ] TLS terminated at reverse proxy
- [ ] CORS allowlist set (not `*` in production unless intentional)
- [ ] Upload limits left at defaults or tuned for your FIT sizes
- [ ] Rate limiting configured for expected traffic profile (account for `workers × replicas` if using in-app limiter)
- [ ] Decide tenant policy: set `DIGITAL_TWIN_REQUIRE_ATHLETE_ID=true` when clients are ready
- [ ] Production auth: set `DIGITAL_TWIN_AUTH_MODE=jwt` with OIDC JWKS (or `api_key` for integrations)
- [ ] JWT claims must include `roles` and `athlete_ids` (or `athlete_id` for athlete role)
- [ ] Roles: `admin`, `owner`, `coach`, `assistant_coach`, `athlete`
- [ ] No secrets in repo — env only
- [ ] Log aggregation for 5xx (FastAPI logs exceptions server-side)

## CI parity before deploy

On the release commit:

```bash
make check
```

Or trigger GitHub Actions **Full backend check** (`workflow_dispatch`).

## Related

- `docs/FRONTEND_CONNECT_NEXT_VERCEL.md` — connect Vercel frontend
- `docs/TROUBLESHOOTING.md` — ops issues
- `Makefile` — `make run`, `make check`
