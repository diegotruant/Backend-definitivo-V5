"""Engine product-quality gate — public entry points with minimal realistic inputs."""

from __future__ import annotations

import pytest

from tests.engine_output_quality import ENGINE_CASES, _run


@pytest.mark.parametrize("case", ENGINE_CASES, ids=lambda c: c.case_id)
def test_engine_product_quality(case) -> None:
    _run(case)
