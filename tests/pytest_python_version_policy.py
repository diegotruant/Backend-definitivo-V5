from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_pyproject() -> dict[str, object]:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_release_gate_runs_on_python_311() -> None:
    assert sys.version_info[:2] == (3, 11)


def test_package_and_tooling_target_python_311() -> None:
    payload = _load_pyproject()
    project = payload["project"]
    tools = payload["tool"]

    assert isinstance(project, dict)
    assert isinstance(tools, dict)
    assert project["requires-python"] == ">=3.11,<3.12"

    black = tools["black"]
    ruff = tools["ruff"]
    mypy = tools["mypy"]
    assert isinstance(black, dict)
    assert isinstance(ruff, dict)
    assert isinstance(mypy, dict)
    assert black["target-version"] == ["py311"]
    assert ruff["target-version"] == "py311"
    assert mypy["python_version"] == "3.11"


def test_docker_and_github_actions_use_python_311() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert dockerfile.startswith("FROM python:3.11-")

    workflow_versions: dict[str, list[str]] = {}
    pattern = re.compile(r"^\s*python-version:\s*[\"']?([^\"'\s]+)", re.MULTILINE)
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        versions = pattern.findall(path.read_text(encoding="utf-8"))
        if versions:
            workflow_versions[str(path.relative_to(ROOT))] = versions

    assert workflow_versions, "No GitHub Actions Python version declarations found"
    assert all(version == "3.11" for versions in workflow_versions.values() for version in versions)
