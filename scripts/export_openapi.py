#!/usr/bin/env python3
"""Export the canonical OpenAPI document to openapi/openapi.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api_app import app  # noqa: E402


def main() -> None:
    out_dir = ROOT / "openapi"
    out_dir.mkdir(parents=True, exist_ok=True)
    schema = app.openapi()
    json_path = out_dir / "openapi.json"
    json_path.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {json_path} ({len(schema.get('paths', {}))} paths)")


if __name__ == "__main__":
    main()
