# Python version policy

## Official runtime

The backend officially supports **Python 3.11.x** only.

This is the release-qualified baseline used by:

- package metadata in `pyproject.toml`;
- Docker production image;
- GitHub Actions workflows;
- mypy semantic target;
- Ruff syntax target;
- Black syntax target;
- the full release gate (`make check`).

The package therefore declares:

```toml
requires-python = ">=3.11,<3.12"
```

## Unsupported versions

### Python 3.10

Python 3.10 is no longer supported. Local environments and deployments must be upgraded to Python 3.11 before installing the package.

### Python 3.12 and 3.13

They are not release-qualified. Do not use them in production until a dedicated compatibility pull request:

1. updates `requires-python`;
2. adds the version to CI;
3. runs the full test, hardening, API matrix and coverage gates;
4. checks NumPy, SciPy, FIT parsing and typing dependencies;
5. updates Docker, mypy, Ruff, Black and documentation consistently.

### Python 3.14+

It is explicitly unsupported until the dependency and stub audit is completed. In particular, the current FIT stack still contains compatibility debt around deprecated datetime APIs.

## Upgrade rule

A Python-version change is a backend runtime compatibility change and must be isolated in one pull request. The pull request must declare:

```text
FRONTEND IMPACT: NONE
BACKEND RUNTIME COMPATIBILITY: BREAKING or ADDITIVE
```

No Python version may be advertised as supported solely because the source code imports successfully. It must pass the repository's official CI and release gate.

## Drift protection

`tests/pytest_python_version_policy.py` verifies that package metadata, tooling, Docker and GitHub Actions remain aligned to Python 3.11.
