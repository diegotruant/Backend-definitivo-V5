"""TwinState serialization helpers."""

from __future__ import annotations

import json
from typing import Any, Dict

from .models import validate_twin_state


def dumps_twin_state(state: Dict[str, Any]) -> str:
    return json.dumps(validate_twin_state(state), ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def loads_twin_state(raw: str) -> Dict[str, Any]:
    return validate_twin_state(json.loads(raw))
