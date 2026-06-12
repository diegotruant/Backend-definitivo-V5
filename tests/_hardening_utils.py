from __future__ import annotations

import contextlib
import math
import signal
from typing import Any, Iterator



@contextlib.contextmanager
def deadline(seconds: float) -> Iterator[None]:
    """Fail a test if a synchronous code path exceeds a wall-clock deadline.

    The project is Linux-based in CI. If SIGALRM is unavailable, the context
    still runs without a timer instead of making the suite platform-hostile.
    """
    if not hasattr(signal, "SIGALRM"):
        yield
        return

    def _handler(_signum: int, _frame: Any) -> None:
        raise TimeoutError(f"operation exceeded {seconds:.2f}s hardening deadline")

    previous = signal.signal(signal.SIGALRM, _handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, previous)


def assert_json_safe(obj: Any, path: str = "root") -> None:
    """Recursively assert that a payload can be safely serialized as JSON."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            assert isinstance(key, (str, int, float, bool, type(None))), f"bad key type at {path}: {type(key)}"
            assert_json_safe(value, f"{path}.{key}")
    elif isinstance(obj, (list, tuple)):
        for idx, value in enumerate(obj):
            assert_json_safe(value, f"{path}[{idx}]")
    elif isinstance(obj, float):
        assert math.isfinite(obj), f"non-finite float at {path}: {obj}"
    else:
        # JSONResponse will convert primitives; custom objects should not leak.
        assert obj is None or isinstance(obj, (str, int, bool)), f"non-JSON primitive at {path}: {type(obj)}"


def finite_score(value: Any, *, allow_none: bool = False) -> None:
    if value is None and allow_none:
        return
    assert isinstance(value, (int, float))
    assert math.isfinite(float(value))
