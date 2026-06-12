"""
Backward-compatibility re-export.

The production code now lives in engines/performance/effort_extractor.py.
This shim keeps existing scripts (test suites, manual runners) working.
"""
from engines.performance.effort_extractor import *  # noqa: F401,F403
from engines.performance.effort_extractor import extract_test_proposal  # noqa: F401 — explicit for clarity
