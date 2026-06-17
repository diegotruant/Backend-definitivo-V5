"""Auth configuration from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

AuthMode = Literal["none", "api_key", "jwt"]


def _parse_csv_set(raw: str) -> set[str]:
    return {item.strip() for item in raw.split(",") if item.strip()}


def _parse_key_prefix_map(raw: str) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for chunk in (part.strip() for part in raw.split(",") if part.strip()):
        if ":" not in chunk:
            continue
        key, prefixes = chunk.split(":", 1)
        key = key.strip()
        pref_list = [p.strip() for p in prefixes.split("|") if p.strip()]
        if key and pref_list:
            mapping[key] = pref_list
    return mapping


@dataclass(frozen=True)
class AuthConfig:
    mode: AuthMode
    require_athlete_id: bool
    valid_api_keys: frozenset[str]
    api_key_athlete_prefixes: dict[str, list[str]]
    jwt_secret: str | None
    jwt_algorithms: tuple[str, ...]
    jwt_audience: str | None
    jwt_issuer: str | None
    jwt_jwks_url: str | None
    athlete_scoped_prefixes: tuple[str, ...]
    protected_prefixes: tuple[str, ...]

    @property
    def auth_enabled(self) -> bool:
        return self.mode != "none"


def load_auth_config() -> AuthConfig:
    mode_raw = os.getenv("DIGITAL_TWIN_AUTH_MODE", "").strip().lower()
    api_key_legacy = os.getenv("DIGITAL_TWIN_API_KEY_AUTH_ENABLED", "false").lower() == "true"
    if mode_raw in {"", "none"} and api_key_legacy:
        mode: AuthMode = "api_key"
    elif mode_raw in {"none", "api_key", "jwt"}:
        mode = mode_raw  # type: ignore[assignment]
    else:
        mode = "none"

    athlete_scoped = (
        "/ride",
        "/profile",
        "/workouts",
        "/twin",
        "/projection",
        "/performance",
        "/load",
        "/team",
        "/history",
        "/readiness",
        "/planning",
    )
    protected = athlete_scoped + ("/test",)

    jwt_algos_raw = os.getenv("DIGITAL_TWIN_JWT_ALGORITHMS", "HS256")
    algorithms = tuple(a.strip() for a in jwt_algos_raw.split(",") if a.strip()) or ("HS256",)

    return AuthConfig(
        mode=mode,
        require_athlete_id=os.getenv("DIGITAL_TWIN_REQUIRE_ATHLETE_ID", "false").lower() == "true",
        valid_api_keys=frozenset(_parse_csv_set(os.getenv("DIGITAL_TWIN_API_KEYS", ""))),
        api_key_athlete_prefixes=_parse_key_prefix_map(
            os.getenv("DIGITAL_TWIN_API_KEY_ATHLETE_PREFIXES", "")
        ),
        jwt_secret=os.getenv("DIGITAL_TWIN_JWT_SECRET") or None,
        jwt_algorithms=algorithms,
        jwt_audience=os.getenv("DIGITAL_TWIN_JWT_AUDIENCE") or None,
        jwt_issuer=os.getenv("DIGITAL_TWIN_JWT_ISSUER") or None,
        jwt_jwks_url=os.getenv("DIGITAL_TWIN_JWT_JWKS_URL") or None,
        athlete_scoped_prefixes=athlete_scoped,
        protected_prefixes=protected,
    )
