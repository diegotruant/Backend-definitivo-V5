"""Pytest bridge for the repository's executable test scripts."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parent
SCRIPT_TESTS = sorted((ROOT / "tests" / "integration").glob("test_*.py"))


@pytest.mark.parametrize("script_path", SCRIPT_TESTS, ids=lambda path: path.name)
def test_executable_script(script_path):
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, (
        f"{script_path.name} failed with exit code {result.returncode}\n"
        f"STDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )
