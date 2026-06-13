"""OpenAPI schema customization."""

from __future__ import annotations

from typing import Any, Dict


def enrich_openapi_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Add deployment metadata used by frontend codegen and docs."""
    schema["servers"] = [
        {"url": "http://localhost:8000", "description": "Local development"},
        {
            "url": "{baseUrl}",
            "description": "Configurable deployment",
            "variables": {
                "baseUrl": {
                    "default": "http://localhost:8000",
                    "description": "Set via VITE_API_BASE_URL in the frontend",
                },
            },
        },
    ]
    schema["externalDocs"] = {
        "description": "Frontend integration guide",
        "url": "https://github.com/diegotruant/Backend-definitivo-V5/blob/main/docs/FRONTEND_DEVELOPER_GUIDE.md",
    }
    info = schema.setdefault("info", {})
    info["x-codegen"] = {
        "typescript_output": "frontend/src/api/generated/schema.ts",
        "regenerate": "make openapi-frontend",
    }
    return schema
