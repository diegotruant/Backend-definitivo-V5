"""Request authentication orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from api.auth.config import AuthConfig
from api.auth.jwt import decode_bearer_token
from api.auth.principal import Principal
from engines.core.security import safe_error_detail


@dataclass(frozen=True)
class AuthResult:
    ok: bool
    status_code: int | None = None
    body: dict[str, Any] | None = None
    principal: Principal | None = None
    athlete_id: str | None = None
    api_key: str | None = None


def _extract_bearer(authorization: str | None) -> str:
    header = (authorization or "").strip()
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return ""


def _missing_athlete_response() -> AuthResult:
    return AuthResult(
        ok=False,
        status_code=400,
        body={
            "detail": {
                "error": "MISSING_ATHLETE_ID",
                "message": "Missing required X-Athlete-Id header for athlete-scoped endpoint.",
            }
        },
    )


def _forbidden() -> AuthResult:
    return AuthResult(ok=False, status_code=403, body=safe_error_detail("FORBIDDEN"))


def _unauthorized() -> AuthResult:
    return AuthResult(ok=False, status_code=401, body=safe_error_detail("UNAUTHORIZED"))


def authenticate_request(
    *,
    path: str,
    authorization: str | None,
    athlete_header: str | None,
    config: AuthConfig,
) -> AuthResult:
    athlete_scoped = path.startswith(config.athlete_scoped_prefixes)
    protected = path.startswith(config.protected_prefixes)

    if config.mode == "none":
        if config.require_athlete_id and athlete_scoped:
            athlete_id = (athlete_header or "").strip()
            if not athlete_id:
                return _missing_athlete_response()
            return AuthResult(ok=True, athlete_id=athlete_id)
        return AuthResult(ok=True)

    if not protected:
        return AuthResult(ok=True)

    token = _extract_bearer(authorization)
    if not token:
        return _unauthorized()

    if config.mode == "api_key":
        if token not in config.valid_api_keys:
            return _unauthorized()
        scoped_athlete: str | None = None
        if config.require_athlete_id and athlete_scoped:
            scoped_athlete = (athlete_header or "").strip()
            if not scoped_athlete:
                return _missing_athlete_response()
            allowed_prefixes = config.api_key_athlete_prefixes.get(token, [])
            if allowed_prefixes and not any(scoped_athlete.startswith(p) for p in allowed_prefixes):
                return _forbidden()
        return AuthResult(ok=True, api_key=token, athlete_id=scoped_athlete)

    # JWT mode
    try:
        claims = decode_bearer_token(token, config)
        principal = Principal.from_claims(claims)
    except Exception:
        return _unauthorized()

    if not principal.subject:
        return _unauthorized()

    if not principal.can_access_path(path):
        return _forbidden()

    jwt_scoped_athlete: str | None = None
    if athlete_scoped or config.require_athlete_id:
        resolved = principal.resolve_athlete_id(athlete_header)
        if not resolved:
            if "athlete" in principal.roles:
                return _forbidden()
            return _missing_athlete_response()
        if not principal.can_access_athlete(resolved):
            return _forbidden()
        jwt_scoped_athlete = resolved

    return AuthResult(ok=True, principal=principal, athlete_id=jwt_scoped_athlete)
