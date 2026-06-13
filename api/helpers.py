"""Backward-compatible re-exports — prefer importing from focused api/* modules."""

from __future__ import annotations

import logging

from api.activity_streams import load_activity_stream, stream_from_power
from api.parsing import (
    athlete_context,
    athlete_context_from_params,
    coerce_stored_curve,
    parse_iso_date,
    parse_metabolic_snapshot,
)
from api.serialization import json_response, nan_to_none
from api.upload import parse_upload

logger = logging.getLogger("digital_twin.api")

__all__ = [
    "athlete_context",
    "athlete_context_from_params",
    "coerce_stored_curve",
    "json_response",
    "load_activity_stream",
    "logger",
    "nan_to_none",
    "parse_iso_date",
    "parse_metabolic_snapshot",
    "parse_upload",
    "stream_from_power",
]
