"""JWT verification for OIDC/OAuth bearer tokens."""

from __future__ import annotations

from typing import Any

from api.auth.config import AuthConfig

try:
    import jwt
    from jwt import PyJWKClient
except ImportError:  # pragma: no cover
    jwt = None  # type: ignore[assignment]
    PyJWKClient = None  # type: ignore[assignment,misc]

_JWKS_CLIENT: PyJWKClient | None = None


def _get_jwks_client(url: str) -> PyJWKClient:
    global _JWKS_CLIENT
    if _JWKS_CLIENT is None or getattr(_JWKS_CLIENT, "uri", None) != url:
        _JWKS_CLIENT = PyJWKClient(url)
    return _JWKS_CLIENT


def decode_bearer_token(token: str, config: AuthConfig) -> dict[str, Any]:
    if jwt is None:
        raise RuntimeError("PyJWT is required for JWT auth: pip install PyJWT")

    options = {"verify_aud": bool(config.jwt_audience)}
    decode_kwargs: dict[str, Any] = {
        "algorithms": list(config.jwt_algorithms),
        "options": options,
    }
    if config.jwt_audience:
        decode_kwargs["audience"] = config.jwt_audience
    if config.jwt_issuer:
        decode_kwargs["issuer"] = config.jwt_issuer

    if config.jwt_jwks_url:
        client = _get_jwks_client(config.jwt_jwks_url)
        signing_key = client.get_signing_key_from_jwt(token)
        return jwt.decode(token, signing_key.key, **decode_kwargs)

    if not config.jwt_secret:
        raise RuntimeError(
            "JWT auth requires DIGITAL_TWIN_JWT_SECRET (HS256) or DIGITAL_TWIN_JWT_JWKS_URL (RS256)"
        )
    return jwt.decode(token, config.jwt_secret, **decode_kwargs)
