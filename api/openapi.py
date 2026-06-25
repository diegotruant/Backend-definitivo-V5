"""OpenAPI schema customization."""

from __future__ import annotations

from typing import Any, Dict


def _normalize_binary_file_schema(node: Any) -> None:
    """Keep generated UploadFile schemas stable across Pydantic/FastAPI versions."""
    if isinstance(node, dict):
        if node.get("contentMediaType") == "application/octet-stream":
            node.pop("contentMediaType", None)
            node.setdefault("format", "binary")
        for value in node.values():
            _normalize_binary_file_schema(value)
    elif isinstance(node, list):
        for item in node:
            _normalize_binary_file_schema(item)


def enrich_openapi_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Add deployment metadata used by frontend codegen and docs."""
    components = schema.setdefault("components", {})
    components["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT or API key",
            "description": (
                "JWT from your OIDC provider (DIGITAL_TWIN_AUTH_MODE=jwt) or static API key "
                "(DIGITAL_TWIN_AUTH_MODE=api_key). Athlete-scoped routes also require X-Athlete-Id."
            ),
        },
        "AthleteIdHeader": {
            "type": "apiKey",
            "in": "header",
            "name": "X-Athlete-Id",
            "description": "Target athlete identifier for coach/admin scoped requests.",
        },
    }
    athlete_prefixes = (
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
        "/test",
    )
    for route_path, path_item in schema.get("paths", {}).items():
        for operation in path_item.values():
            if not isinstance(operation, dict) or "operationId" not in operation:
                continue
            if route_path.startswith(athlete_prefixes):
                operation["security"] = [{"BearerAuth": []}, {"AthleteIdHeader": []}]
    schema["servers"] = [
        {"url": "http://localhost:8000", "description": "Local development"},
        {
            "url": "{baseUrl}",
            "description": "Configurable deployment",
            "variables": {
                "baseUrl": {
                    "default": "http://localhost:8000",
                    "description": (
                        "Frontend env: VITE_API_BASE_URL (Vite) or "
                        "NEXT_PUBLIC_API_BASE_URL (Next.js/Vercel/v0)"
                    ),
                },
            },
        },
    ]
    schema["externalDocs"] = {
        "description": "Frontend integration guide",
        "url": "https://github.com/diegotruant/Backend-definitivo-V5/blob/main/docs/OPENAPI_FRONTEND.md",
    }
    _normalize_binary_file_schema(schema)
    info = schema.setdefault("info", {})
    info["x-codegen"] = {
        "typescript_output": "frontend/src/api/generated/schema.ts",
        "regenerate": "make openapi-frontend",
        "frontend_env_vars": ["VITE_API_BASE_URL", "NEXT_PUBLIC_API_BASE_URL"],
    }
    return schema
