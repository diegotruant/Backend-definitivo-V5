"""Compatibility wrapper for the HRV engine module."""

from importlib import import_module

_impl = import_module("hrv_engine")

analyze_rr_stream = _impl.analyze_rr_stream
calculate_dfa_alpha1 = _impl.calculate_dfa_alpha1

__all__ = ["analyze_rr_stream", "calculate_dfa_alpha1"]
