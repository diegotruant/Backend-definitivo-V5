"""
FIT Parser — Enhanced with Gap Handling
Version: 2.0.0-GapAware

NEW FEATURES:
- Intelligent interpolation for sensor dropouts
- Data quality flags per sample
- Gap detection and classification

GAP HANDLING STRATEGY:
  - Gap <10s:   Linear interpolation (sensor glitch)
  - Gap 10-60s: Forward-fill (dropout)
  - Gap >60s:   Mark as UNRELIABLE (exclude from calculations)
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from io import BytesIO
import time
import numpy as np

try:
    import fitdecode
    from fitdecode import FitCRCError, FitEOFError, FitError, FitHeaderError, FitParseError
    FITDECODE_AVAILABLE = True
except ImportError:  # pragma: no cover
    FITDECODE_AVAILABLE = False
    class FitError(Exception): ...  # type: ignore[no-redef]
    class FitParseError(FitError): ...  # type: ignore[no-redef]
    class FitEOFError(FitParseError): ...  # type: ignore[no-redef]
    class FitCRCError(FitParseError): ...  # type: ignore[no-redef]
    class FitHeaderError(FitParseError): ...  # type: ignore[no-redef]

try:
    import fitparse
    from fitparse.utils import (
        FitCRCError as FitParseCRCError,
        FitEOFError as FitParseEOFError,
        FitHeaderError as FitParseHeaderError,
        FitParseError as FitParseLibError,
    )
    FITPARSE_AVAILABLE = True
except ImportError:  # pragma: no cover
    FITPARSE_AVAILABLE = False
    class FitParseLibError(Exception): ...  # type: ignore[no-redef]
    class FitParseEOFError(FitParseLibError): ...  # type: ignore[no-redef]
    class FitParseCRCError(FitParseLibError): ...  # type: ignore[no-redef]
    class FitParseHeaderError(FitParseLibError): ...  # type: ignore[no-redef]

# Canonical capability flags. FITPARSE_AVAILABLE now means exactly what its
# name says: the legacy fitparse fallback is installed. General parser
# availability is represented separately and remains backward-compatible via
# FIT_BACKEND_AVAILABLE.
FITPARSE_FALLBACK_AVAILABLE = FITPARSE_AVAILABLE
FIT_PARSER_AVAILABLE = FITDECODE_AVAILABLE or FITPARSE_FALLBACK_AVAILABLE
FIT_BACKEND_AVAILABLE = FIT_PARSER_AVAILABLE
FIT_PARSER_VERSION = "2.0.1-gapaware"


class FitFileError(Exception):
    """Raised when a .FIT file cannot be parsed.

    A single, typed exception that callers can catch instead of reaching into
    fitparse's internal error hierarchy. Carries a machine-readable `reason`
    so the API layer can return a clean 4xx with a stable error code instead
    of leaking a library stack trace as a 500.

    reason codes:
      EMPTY_FILE          — file is empty or far too small to be a FIT
      INVALID_HEADER      — not a FIT file / header unreadable
      TRUNCATED           — file ends mid-record (incomplete download/transfer)
      CRC_MISMATCH         — CRC failed and the file could not be recovered
      MALFORMED_RECORDS   — header ok but record stream is corrupt
      NO_RECORDS          — parsed cleanly but contains zero usable data records
      UNKNOWN             — any other parse failure
    """

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


def _read_file_with_retry(path: str, attempts: int = 3, delay_s: float = 0.25) -> bytes:
    """
    Read a file's bytes, retrying on transient I/O errors.

    Cloud/network-backed storage (S3, GCS, NFS) occasionally raises
    OSError errno 5 (EIO) on the first read of a freshly-written file.
    A short retry resolves it without affecting genuinely missing or
    corrupt files (which raise FileNotFoundError / persistent OSError).
    """
    last_err = None
    for i in range(attempts):
        try:
            with open(path, "rb") as fh:
                return fh.read()
        except FileNotFoundError:
            raise  # don't retry a missing file
        except OSError as e:
            last_err = e
            if i < attempts - 1:
                time.sleep(delay_s * (i + 1))  # linear backoff
    raise last_err


# Quality flags
QUALITY_GOOD = 0
QUALITY_INTERPOLATED = 1  # Gap <10s, linear interpolation
QUALITY_FORWARD_FILLED = 2  # Gap 10-60s, last known value
QUALITY_UNRELIABLE = 3  # Gap >60s, data missing


class ActivityStreamEnhanced:
    """
    Activity stream with data quality tracking.
    
    Field naming convention:
      - Direct physical quantities use unambiguous names: `power`, `heart_rate`,
        `cadence` (no unit suffix — they're conventionally Watts, bpm, rpm)
      - Quantities with non-trivial units keep the suffix: `altitude_m`,
        `distance_m`, `speed_mps`, `temperature_c`
      - Computed/derived booleans (has_power, has_heart_rate, has_rr) and
        aggregates (total_distance_m, total_ascent_m) are properties, not fields
    
    Per-sample arrays (length = n_samples):
        elapsed_s, lat, lon, altitude_m, distance_m,
        power, heart_rate, cadence, speed_mps, temperature_c,
        quality_power, quality_hr, rr_intervals
    
    Scalars:
        n_samples, sport, sub_sport, device_name, start_time,
        total_elapsed_s, gap_summary
    """
    
    def __init__(
        self,
        n_samples: int,
        sport: str = "cycling",
        sub_sport: Optional[str] = None,
        device_name: Optional[str] = None,
        start_time: Optional[datetime] = None,
        total_elapsed_s: Optional[float] = None,
    ):
        self.n_samples = n_samples
        self.sport = sport
        self.sub_sport = sub_sport
        self.device_name = device_name
        self.start_time = start_time
        self.total_elapsed_s = total_elapsed_s
        
        # Time and position
        self.elapsed_s = np.zeros(n_samples, dtype=np.float32)
        self.lat = np.full(n_samples, np.nan, dtype=np.float32)
        self.lon = np.full(n_samples, np.nan, dtype=np.float32)
        self.altitude_m = np.full(n_samples, np.nan, dtype=np.float32)
        self.distance_m = np.full(n_samples, np.nan, dtype=np.float32)
        
        # Core metrics (canonical names — no compat aliases)
        self.power = np.zeros(n_samples, dtype=np.float32)
        self.heart_rate = np.zeros(n_samples, dtype=np.float32)
        self.cadence = np.zeros(n_samples, dtype=np.float32)
        self.speed_mps = np.full(n_samples, np.nan, dtype=np.float32)
        self.temperature_c = np.full(n_samples, np.nan, dtype=np.float32)
        
        # Left/Right pedaling balance (% of total power generated by LEFT leg)
        # NaN when not provided by the sensor. Only meaningful when the source
        # is a dual-side power meter; the parser sets `pedaling_balance_source`
        # to "dual" | "single_estimated" | "unknown" based on device_info.
        self.left_right_balance = np.full(n_samples, np.nan, dtype=np.float32)
        self.pedaling_balance_source: str = "unknown"

        # Cycling dynamics / pedaling efficiency metrics. Values are NaN when
        # absent. These are parsed as raw scalar time-series so chart builders
        # can decide how to render them without re-reading the FIT.
        self.left_power_phase = np.full(n_samples, np.nan, dtype=np.float32)
        self.right_power_phase = np.full(n_samples, np.nan, dtype=np.float32)
        self.left_power_phase_peak = np.full(n_samples, np.nan, dtype=np.float32)
        self.right_power_phase_peak = np.full(n_samples, np.nan, dtype=np.float32)
        self.left_pco = np.full(n_samples, np.nan, dtype=np.float32)
        self.right_pco = np.full(n_samples, np.nan, dtype=np.float32)
        self.left_pedal_smoothness = np.full(n_samples, np.nan, dtype=np.float32)
        self.right_pedal_smoothness = np.full(n_samples, np.nan, dtype=np.float32)
        self.left_torque_effectiveness = np.full(n_samples, np.nan, dtype=np.float32)
        self.right_torque_effectiveness = np.full(n_samples, np.nan, dtype=np.float32)
        self.respiration_rate = np.full(n_samples, np.nan, dtype=np.float32)
        # Standing/seated position (0=seated, 1=standing) and dynamics flags.
        self.cadence_position = np.full(n_samples, np.nan, dtype=np.float32)
        self.has_cycling_dynamics: bool = False
        self.has_respiration: bool = False
        
        # Core body temperature and skin temperature (from a body-temperature sensor)
        # NaN when not provided. core_body_temp is the primary metric (°C),
        # skin_temp is secondary. ambient_temp is from the head unit's
        # built-in thermometer (not from the body-temperature sensor).
        self.core_body_temp = np.full(n_samples, np.nan, dtype=np.float32)
        self.skin_temp = np.full(n_samples, np.nan, dtype=np.float32)
        self.ambient_temp = np.full(n_samples, np.nan, dtype=np.float32)
        self.has_core_sensor: bool = False
        
        # Quality flags
        self.quality_power = np.full(n_samples, QUALITY_GOOD, dtype=np.uint8)
        self.quality_hr = np.full(n_samples, QUALITY_GOOD, dtype=np.uint8)
        
        # RR intervals (per-sample list of beat intervals, may be empty)
        self.rr_intervals: List[List[float]] = [[] for _ in range(n_samples)]
        
        # Gap summary (populated by parser)
        self.gap_summary: Dict[str, Any] = {}
        # Lap markers extracted from FIT lap messages (empty for JSON-only streams).
        self.laps: List[Dict[str, Any]] = []
        # Provenance metadata for API consumers (FIT vs power_json, synthetic flags).
        self.data_provenance: Dict[str, Any] = {}
    
    # =========================================================================
    # Computed properties (lightweight — recomputed on access)
    # =========================================================================
    
    @property
    def has_power(self) -> bool:
        return bool(np.any(self.power > 0))
    
    @property
    def has_heart_rate(self) -> bool:
        return bool(np.any(self.heart_rate > 0))
    
    @property
    def has_rr(self) -> bool:
        return any(len(rr) > 0 for rr in self.rr_intervals)

    @property
    def has_speed(self) -> bool:
        return bool(np.any(np.isfinite(self.speed_mps) & (self.speed_mps > 0)))

    @property
    def has_distance(self) -> bool:
        return bool(np.any(np.isfinite(self.distance_m)))

    @property
    def has_altitude(self) -> bool:
        return bool(np.any(np.isfinite(self.altitude_m)))
    
    @property
    def total_distance_m(self) -> float:
        if self.distance_m.size == 0 or not self.has_distance:
            return 0.0
        return float(np.nanmax(self.distance_m))
    
    @property
    def total_ascent_m(self) -> Optional[float]:
        if self.altitude_m.size < 2 or np.all(np.isnan(self.altitude_m)):
            return None
        diffs = np.diff(self.altitude_m)
        positives = diffs[diffs > 0]
        return float(np.nansum(positives)) if positives.size else 0.0

    # ---------------------------------------------------------------------
    # Compatibility aliases used by the product chart envelope.
    # The canonical stream names remain elapsed_s / altitude_m / speed_mps /
    # temperature_c / core_body_temp / skin_temp, but the chart package expects
    # stream.time, stream.altitude, stream.speed, etc. Keep both conventions.
    # ---------------------------------------------------------------------
    @property
    def time(self) -> np.ndarray:
        return self.elapsed_s

    @property
    def altitude(self) -> np.ndarray:
        # Prefer enhanced_altitude when it has data; fall back to standard
        # altitude. enhanced_altitude is mapped into altitude_m at parse time.
        return self.altitude_m

    @property
    def speed(self) -> np.ndarray:
        return self.speed_mps

    @property
    def temperature(self) -> np.ndarray:
        return self.temperature_c

    @property
    def core_temperature(self) -> np.ndarray:
        return self.core_body_temp

    @property
    def skin_temperature(self) -> np.ndarray:
        return self.skin_temp


def detect_and_fill_gaps(
    values: np.ndarray,
    quality: np.ndarray,
    elapsed: np.ndarray,
    gap_short_s: float = 10.0,
    gap_long_s: float = 60.0,
    zero_is_missing: bool = True,
) -> tuple[np.ndarray, np.ndarray, dict]:
    """
    Detect gaps in data and apply appropriate filling strategy.
    
    Parameters:
        values: Data array (power, HR, etc)
        quality: Quality flags array (modified in-place)
        elapsed: Elapsed time array
        gap_short_s: Threshold for linear interpolation (default 10s)
        gap_long_s: Threshold for unreliable marking (default 60s)
    
    Returns:
        (filled_values, updated_quality, gap_stats)
    
    Gap handling:
        - Missing data (value=0 for power/HR) with dt < gap_short_s → interpolate
        - Missing data with gap_short_s <= dt < gap_long_s → forward-fill
        - Missing data with dt >= gap_long_s → mark unreliable
    """
    n = len(values)
    filled = values.copy()
    
    gaps_detected = []
    gaps_interpolated = 0
    gaps_forward_filled = 0
    gaps_unreliable = 0
    
    # Missing data: 0W power is valid (coasting), 0 bpm HR is not.
    if zero_is_missing:
        missing_mask = (values == 0) | np.isnan(values)
    else:
        missing_mask = np.isnan(values)
    
    if not missing_mask.any():
        return filled, quality, {
            "n_gaps": 0,
            "interpolated": 0,
            "forward_filled": 0,
            "unreliable": 0,
        }
    
    # Detect contiguous gap regions
    i = 0
    while i < n:
        if not missing_mask[i]:
            i += 1
            continue
        
        # Found gap start
        gap_start = i
        while i < n and missing_mask[i]:
            i += 1
        gap_end = i  # exclusive
        
        gap_duration_s = elapsed[gap_end - 1] - (elapsed[gap_start - 1] if gap_start > 0 else 0)
        gap_length = gap_end - gap_start
        
        gaps_detected.append({
            "start_idx": gap_start,
            "end_idx": gap_end,
            "duration_s": gap_duration_s,
            "n_samples": gap_length,
        })
        
        # Apply filling strategy
        if gap_duration_s < gap_short_s:
            # Linear interpolation
            if gap_start > 0 and gap_end < n:
                val_before = filled[gap_start - 1]
                val_after = filled[gap_end]
                interp_vals = np.linspace(val_before, val_after, gap_length + 2)[1:-1]
                filled[gap_start:gap_end] = interp_vals
                quality[gap_start:gap_end] = QUALITY_INTERPOLATED
                gaps_interpolated += 1
            elif gap_start == 0 and gap_end < n:
                # Gap at start → forward-fill from first valid
                filled[gap_start:gap_end] = filled[gap_end]
                quality[gap_start:gap_end] = QUALITY_FORWARD_FILLED
                gaps_forward_filled += 1
            else:
                # Gap at end → backward-fill
                filled[gap_start:gap_end] = filled[gap_start - 1]
                quality[gap_start:gap_end] = QUALITY_FORWARD_FILLED
                gaps_forward_filled += 1
        
        elif gap_duration_s < gap_long_s:
            # Forward-fill
            if gap_start > 0:
                filled[gap_start:gap_end] = filled[gap_start - 1]
                quality[gap_start:gap_end] = QUALITY_FORWARD_FILLED
                gaps_forward_filled += 1
            else:
                # Gap at start with no prior value → mark unreliable
                quality[gap_start:gap_end] = QUALITY_UNRELIABLE
                gaps_unreliable += 1
        
        else:
            # Long gap → unreliable
            quality[gap_start:gap_end] = QUALITY_UNRELIABLE
            gaps_unreliable += 1
    
    gap_stats = {
        "n_gaps": len(gaps_detected),
        "interpolated": gaps_interpolated,
        "forward_filled": gaps_forward_filled,
        "unreliable": gaps_unreliable,
        "gap_details": gaps_detected if len(gaps_detected) < 50 else gaps_detected[:50],  # Limit size
    }
    
    return filled, quality, gap_stats


def measured_signal_flags(stream: ActivityStreamEnhanced) -> dict[str, bool]:
    """Canonical availability flags shared by parser provenance and quality reports."""
    return {
        "power": bool(stream.has_power),
        "heart_rate": bool(stream.has_heart_rate),
        "cadence": bool(np.any(stream.cadence > 0)),
        "speed": bool(stream.has_speed),
        "distance": bool(stream.has_distance),
        "altitude": bool(stream.has_altitude),
        "gps": bool(np.any(np.isfinite(stream.lat)) and np.any(np.isfinite(stream.lon))),
        "rr": bool(stream.has_rr),
        "temperature": bool(np.any(np.isfinite(stream.temperature_c))),
        "cycling_dynamics": bool(stream.has_cycling_dynamics),
        "respiration": bool(stream.has_respiration),
    }


def _available_measured_signals(stream: ActivityStreamEnhanced) -> list[str]:
    flags = measured_signal_flags(stream)
    ordered = [
        "power",
        "heart_rate",
        "cadence",
        "speed",
        "distance",
        "altitude",
        "gps",
        "latitude",
        "longitude",
        "rr",
        "temperature",
        "cycling_dynamics",
        "respiration",
    ]
    signals: list[str] = []
    for name in ordered:
        if name == "latitude" and flags.get("gps"):
            signals.append("latitude")
        elif name == "longitude" and flags.get("gps"):
            signals.append("longitude")
        elif flags.get(name):
            signals.append(name)
    return signals


def _ensure_utc_datetime(value: Any) -> Any:
    """Normalize FIT timestamps to timezone-aware UTC datetimes."""
    if value is None or not isinstance(value, datetime):
        return value
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _utc_isoformat(value: Any) -> Any:
    """Serialize FIT timestamps as UTC ISO-8601 strings."""
    if value is None:
        return None
    if not hasattr(value, "isoformat"):
        return value
    return _ensure_utc_datetime(value).isoformat()


def normalize_lap_messages(lap_msgs: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    """Normalize FIT lap messages into the effort-extractor contract."""
    laps: list[Dict[str, Any]] = []
    for idx, lap in enumerate(lap_msgs):
        duration_raw = lap.get("total_timer_time")
        if duration_raw is None:
            duration_raw = lap.get("total_elapsed_time")
        if duration_raw is None:
            continue
        try:
            duration_s = int(round(float(duration_raw)))
        except (TypeError, ValueError):
            continue
        if duration_s <= 0:
            continue
        avg_power = lap.get("avg_power")
        max_power = lap.get("max_power")
        avg_hr = lap.get("avg_heart_rate")
        start_time = lap.get("start_time")
        laps.append(
            {
                "lap_index": int(lap.get("message_index", idx)),
                "start_time": _utc_isoformat(start_time),
                "duration_s": duration_s,
                "avg_power_w": float(avg_power) if avg_power is not None else None,
                "max_power_w": float(max_power) if max_power is not None else None,
                "avg_hr": int(avg_hr) if avg_hr is not None else None,
            }
        )
    return laps


def _extract_messages_with_fitdecode(
    payload: bytes,
    *,
    check_crc: bool,
) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]], list[Dict[str, Any]], list[Dict[str, Any]], list[Dict[str, Any]]]:
    """Decode FIT payload with fitdecode into plain dict rows."""
    crc_mode = fitdecode.CrcCheck.RAISE if check_crc else fitdecode.CrcCheck.DISABLED
    records: list[Dict[str, Any]] = []
    sessions: list[Dict[str, Any]] = []
    device_infos: list[Dict[str, Any]] = []
    hrv_msgs: list[Dict[str, Any]] = []
    lap_msgs: list[Dict[str, Any]] = []

    with fitdecode.FitReader(BytesIO(payload), check_crc=crc_mode) as reader:
        for frame in reader:
            if not isinstance(frame, fitdecode.records.FitDataMessage):
                continue
            values = {field.name: field.value for field in frame.fields}
            if frame.name == "record":
                records.append(values)
            elif frame.name == "session":
                sessions.append(values)
            elif frame.name == "device_info":
                device_infos.append(values)
            elif frame.name == "hrv":
                hrv_msgs.append(values)
            elif frame.name == "lap":
                lap_msgs.append(values)
    return records, sessions, device_infos, hrv_msgs, lap_msgs


def _extract_messages_with_fitparse(
    payload: bytes,
    *,
    check_crc: bool,
) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]], list[Dict[str, Any]], list[Dict[str, Any]], list[Dict[str, Any]]]:
    """Decode FIT payload with the legacy fitparse fallback into plain dict rows."""
    if not FITPARSE_FALLBACK_AVAILABLE:
        raise RuntimeError("fitparse fallback backend is not available")
    fitfile = fitparse.FitFile(BytesIO(payload), check_crc=check_crc)
    records: list[Dict[str, Any]] = []
    sessions: list[Dict[str, Any]] = []
    device_infos: list[Dict[str, Any]] = []
    hrv_msgs: list[Dict[str, Any]] = []
    lap_msgs: list[Dict[str, Any]] = []

    for msg in fitfile.get_messages():
        row = {field.name: field.value for field in msg.fields}
        if msg.name == "record":
            records.append(row)
        elif msg.name == "session":
            sessions.append(row)
        elif msg.name == "device_info":
            device_infos.append(row)
        elif msg.name == "hrv":
            hrv_msgs.append(row)
        elif msg.name == "lap":
            lap_msgs.append(row)
    return records, sessions, device_infos, hrv_msgs, lap_msgs


def _extract_messages(
    payload: bytes,
    *,
    check_crc: bool,
) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]], list[Dict[str, Any]], list[Dict[str, Any]], list[Dict[str, Any]]]:
    """Decode FIT payload using fitdecode first, then the legacy fallback."""
    if FITDECODE_AVAILABLE:
        try:
            return _extract_messages_with_fitdecode(payload, check_crc=check_crc)
        except (FitError, FitParseError, FitEOFError, FitHeaderError, FitCRCError):
            if FITPARSE_FALLBACK_AVAILABLE:
                return _extract_messages_with_fitparse(payload, check_crc=check_crc)
            raise
    if FITPARSE_FALLBACK_AVAILABLE:
        return _extract_messages_with_fitparse(payload, check_crc=check_crc)
    raise RuntimeError("No FIT parser backend available. Install fitdecode or fitparse.")


def parse_fit_file_enhanced(
    fit_path: str,
    gap_short_s: float = 10.0,
    gap_long_s: float = 60.0,
    check_crc: bool = True,
    repair_synthetic_header: bool = True,
) -> ActivityStreamEnhanced:
    """
    Parse FIT file with gap detection and intelligent filling.
    
    Parameters:
        fit_path: Path to .fit file
        gap_short_s: Threshold for interpolation (default 10s)
        gap_long_s: Threshold for unreliable marking (default 60s)
        check_crc: Whether the FIT decoder should enforce CRC validation.
            Keep True for real files; synthetic datasets may intentionally
            contain invalid CRCs and can be parsed with False.
        repair_synthetic_header: Repair a known synthetic-file issue where the
            FIT header declares 14 bytes but the data section starts at byte 12.
    
    Returns:
        ActivityStreamEnhanced with quality flags and gap summary
    """
    if not FIT_PARSER_AVAILABLE:
        raise RuntimeError("No FIT parser backend available — install fitdecode (preferred) or fitparse")
    
    raw = None
    if repair_synthetic_header:
        raw = bytearray(_read_file_with_retry(fit_path))
        # NOTE: we no longer pre-classify a file as "bad" from the 0x40 bit,
        # because that misfires on valid files with developer-data records.
        # raw is kept only so the fallback repair path can use it if the
        # normal parse fails.

    # Some synthetic test files declare a 14-byte header but place the data
    # section at byte 12. That repair, however, must NEVER touch a valid file:
    # a legitimate 14-byte header is normal, and the 0x40 bit on the first
    # record header means "developer data", not "corrupt file". So we try to
    # parse the file as-is first, and only attempt the byte-0 repair if normal
    # parsing actually fails.
    try:
        payload = bytes(raw) if raw is not None else _read_file_with_retry(fit_path)
    except Exception as e:
        raise FitFileError("EMPTY_FILE", f"could not read file: {e}") from e

    if len(payload) < 14:
        raise FitFileError(
            "EMPTY_FILE",
            f"file is {len(payload)} bytes — too small to be a FIT file",
        )

    records: list[Dict[str, Any]] = []
    _session_msgs: list[Dict[str, Any]] = []
    _device_info_msgs: list[Dict[str, Any]] = []
    _hrv_msgs: list[Dict[str, Any]] = []
    _lap_msgs: list[Dict[str, Any]] = []

    had_crc_or_eof_error = False
    try:
        records, _session_msgs, _device_info_msgs, _hrv_msgs, _lap_msgs = _extract_messages(
            payload,
            check_crc=check_crc,
        )
    except (FitParseHeaderError, FitHeaderError) as e:
        raise FitFileError("INVALID_HEADER", str(e)) from e
    except (FitParseEOFError, FitEOFError) as e:
        # Partial-truncation recovery path below retries without CRC.
        if "not a FIT file" in str(e):
            raise FitFileError("INVALID_HEADER", str(e)) from e
        had_crc_or_eof_error = True
    except (FitParseCRCError, FitCRCError):
        had_crc_or_eof_error = True
    except (FitParseLibError, FitParseError) as e:
        if "not a FIT file" in str(e):
            raise FitFileError("INVALID_HEADER", str(e)) from e
    except Exception as e:
        if "not a FIT file" in str(e):
            raise FitFileError("INVALID_HEADER", str(e)) from e

    if not records or had_crc_or_eof_error:
        # Recovery attempt: if the only problem was CRC/truncation, payload may
        # still contain readable leading records.
        try:
            records, _session_msgs, _device_info_msgs, _hrv_msgs, _lap_msgs = _extract_messages(
                payload,
                check_crc=False,
            )
        except (FitParseHeaderError, FitHeaderError) as e:
            raise FitFileError("INVALID_HEADER", str(e)) from e
        except (FitParseEOFError, FitEOFError) as e:
            raise FitFileError("TRUNCATED", str(e)) from e
        except (FitParseCRCError, FitCRCError) as e:
            raise FitFileError("CRC_MISMATCH", str(e)) from e
        except (FitParseLibError, FitParseError) as e:
            raise FitFileError("MALFORMED_RECORDS", str(e)) from e
        except Exception as e:
            raise FitFileError("UNKNOWN", str(e)) from e

    if not records:
        raise FitFileError(
            "NO_RECORDS",
            "file parsed but contains no usable data records",
        )

    # Extract session info
    session_dict = {}
    for rec in _session_msgs:
        if rec.get("sport") is not None:
            session_dict["sport"] = rec.get("sport")
        if rec.get("sub_sport") is not None:
            session_dict["sub_sport"] = rec.get("sub_sport")
        if rec.get("start_time") is not None:
            session_dict["start_time"] = _ensure_utc_datetime(rec.get("start_time"))
        if rec.get("total_elapsed_time") is not None:
            session_dict["total_elapsed_time"] = rec.get("total_elapsed_time")
    
    # Extract device info: head unit is usually the first device_info message,
    # but power meters appear as separate entries with their own manufacturer/product.
    # We also need to classify the power meter as dual-side (real L/R) vs
    # single-side (left-only, balance is estimated and unreliable) vs unknown.
    head_unit_set = False
    pm_source = "unknown"   # default
    
    # Identifying dual-side measurement from metadata alone is imperfect.
    # We use generic product-string hints and then let the data-driven fallback
    # below decide from the actual balance samples.
    _DUAL_MARKERS = (
        "duo", "dual", "pair", "left_right", "bilateral", "two_sided",
    )
    _SINGLE_MARKERS = (
        "single", "single_left", "single_l", "left_only", "one_sided",
    )
    
    for rec in _device_info_msgs:
        manufacturer = rec.get("manufacturer")
        product = rec.get("product")
        ant_dev_type = rec.get("antplus_device_type")
        
        # First non-empty entry -> head unit
        if not head_unit_set and (manufacturer or product):
            parts = [str(p) for p in (manufacturer, product) if p]
            session_dict["device_name"] = " ".join(parts)
            head_unit_set = True
            continue
        
        # Subsequent entries: look for power meter
        # ANT+ device type 11 = bike_power (fitparse may return int or string)
        is_power_meter = (
            ant_dev_type in (11, "bike_power")
        ) or (
            manufacturer and "power" in str(manufacturer).lower()
        ) or (
            product and any(m in str(product).lower() for m in (
                "power", "pedal", "crank", "spider", "dual", "single"
            ))
        )
        
        if is_power_meter:
            full = f"{manufacturer} {product}".lower() if (manufacturer or product) else ""
            if any(m in full for m in _DUAL_MARKERS):
                pm_source = "dual"
            elif any(m in full for m in _SINGLE_MARKERS):
                pm_source = "single_estimated"
            # else stays "unknown" — we'll let the data itself decide
    
    # Convert to enhanced stream
    stream = parse_fit_records_enhanced(
        records,
        session_dict=session_dict,
        gap_short_s=gap_short_s,
        gap_long_s=gap_long_s,
    )
    stream.pedaling_balance_source = pm_source
    stream.laps = normalize_lap_messages(_lap_msgs)
    stream.data_provenance = {
        "source": "fit_file",
        "synthetic_signals": [],
        "measured_signals": _available_measured_signals(stream),
    }
    
    # Data-driven fallback: if we couldn't identify the power meter from
    # device_info but the FIT contains left_right_balance data that actually
    # VARIES (not all-50 dummy values), then it must be a dual-side meter.
    # This handles any device not in our marker lists, including future models.
    if pm_source == "unknown":
        valid_balance = stream.left_right_balance[~np.isnan(stream.left_right_balance)]
        if len(valid_balance) >= 60:
            # Check if values actually vary (std > 1 means real measurement,
            # not a dummy 50/50 or a constant value from a single-side meter)
            if valid_balance.std() > 1.0:
                stream.pedaling_balance_source = "dual"
            elif np.all(valid_balance == 50) or valid_balance.std() < 0.5:
                # All 50 or near-constant → single-side estimated
                stream.pedaling_balance_source = "single_estimated"

    # consumer platform stores RR data in dedicated 'hrv' messages (not in record),
    # each containing a 'time' field with a list of beat-to-beat intervals
    # in seconds. We flatten the full sequence, then distribute beats to
    # the nearest record-second bucket by walking elapsed time.
    if _hrv_msgs and not stream.has_rr:
        rr_seq_s: List[float] = []
        for hmsg in _hrv_msgs:
            val = hmsg.get("time")
            if val is not None:
                if isinstance(val, (list, tuple)):
                    rr_seq_s.extend(
                        float(v) for v in val
                        if v is not None and float(v) > 0.0
                    )
                elif float(val) > 0.0:
                    rr_seq_s.append(float(val))
                continue
            for field_name, field_val in hmsg.items():
                if field_name != "time":
                    continue
                val = field_val
                if isinstance(val, (list, tuple)):
                    rr_seq_s.extend(
                        float(v) for v in val
                        if v is not None and float(v) > 0.0
                    )
                elif val is not None and float(val) > 0.0:
                    rr_seq_s.append(float(val))

        if rr_seq_s:
            n_samples = len(stream.elapsed_s)
            beat_cursor_s = 0.0
            rr_idx = 0
            n_rr = len(rr_seq_s)
            for idx in range(n_samples):
                window_end = stream.elapsed_s[idx] + 0.5  # ±0.5s tolerance
                beats_in_window: List[float] = []
                while rr_idx < n_rr:
                    beat_cursor_s += rr_seq_s[rr_idx]
                    if beat_cursor_s <= window_end:
                        beats_in_window.append(rr_seq_s[rr_idx] * 1000.0)  # → ms
                        rr_idx += 1
                    else:
                        beat_cursor_s -= rr_seq_s[rr_idx]
                        break
                if beats_in_window:
                    stream.rr_intervals[idx] = beats_in_window

    return stream


def _field_to_float(value: Any) -> Optional[float]:
    """Best-effort conversion for scalar FIT/developer fields.

    fitparse may expose cycling-dynamics values as floats, ints, dict-like
    wrappers, or short lists/tuples. For chart time-series we store one scalar:
    the first numeric value for ranges/arrays, or the `value` key for dicts.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        for key in ("value", "raw_value", "converted_value"):
            if key in value:
                return _field_to_float(value[key])
        return None
    if isinstance(value, (list, tuple)):
        for item in value:
            converted = _field_to_float(item)
            if converted is not None:
                return converted
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if np.isnan(out) or np.isinf(out):
        return None
    return out


def _copy_first_numeric_field(
    rec: Dict[str, Any],
    fields: tuple[str, ...],
    target: np.ndarray,
    idx: int,
    *,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
) -> None:
    """Copy the first present numeric field into a per-sample stream array."""
    for field in fields:
        if field not in rec:
            continue
        value = _field_to_float(rec.get(field))
        if value is None:
            continue
        if min_value is not None and value < min_value:
            continue
        if max_value is not None and value > max_value:
            continue
        target[idx] = value
        return


def parse_fit_records_enhanced(
    records: List[Dict[str, Any]],
    session_dict: Optional[Dict[str, Any]] = None,
    gap_short_s: float = 10.0,
    gap_long_s: float = 60.0,
) -> ActivityStreamEnhanced:
    """
    Parse FIT records into enhanced activity stream with gap handling.
    """
    session_dict = session_dict or {}
    
    sport = session_dict.get("sport", "cycling")
    sub_sport = session_dict.get("sub_sport")
    device_name = session_dict.get("device_name")
    start_time = _ensure_utc_datetime(session_dict.get("start_time"))
    total_elapsed = session_dict.get("total_elapsed_time")
    
    # Normalize to 1Hz grid
    if total_elapsed:
        n_samples = int(np.ceil(total_elapsed))
    else:
        # Estimate from records
        if records and "timestamp" in records[0] and "timestamp" in records[-1]:
            first_ts = _ensure_utc_datetime(records[0]["timestamp"])
            last_ts = _ensure_utc_datetime(records[-1]["timestamp"])
            dt = (last_ts - first_ts).total_seconds()
            n_samples = int(np.ceil(dt)) + 1
        else:
            n_samples = len(records)
    
    stream = ActivityStreamEnhanced(
        n_samples=n_samples,
        sport=sport,
        sub_sport=sub_sport,
        device_name=device_name,
        start_time=start_time,
        total_elapsed_s=float(n_samples),
    )
    
    # Fill elapsed time grid
    stream.elapsed_s = np.arange(n_samples, dtype=np.float32)
    
    # Map records to 1Hz grid
    for rec in records:
        if "timestamp" not in rec or not start_time:
            continue

        timestamp = _ensure_utc_datetime(rec["timestamp"])
        elapsed = (timestamp - start_time).total_seconds()
        idx = int(np.round(elapsed))
        
        if 0 <= idx < n_samples:
            if "power" in rec and rec["power"] is not None:
                stream.power[idx] = float(rec["power"])
            if "heart_rate" in rec and rec["heart_rate"] is not None:
                stream.heart_rate[idx] = float(rec["heart_rate"])
            if "cadence" in rec and rec["cadence"] is not None:
                stream.cadence[idx] = float(rec["cadence"])
            if "speed" in rec and rec["speed"] is not None:
                stream.speed_mps[idx] = float(rec["speed"])
            elif "enhanced_speed" in rec and rec["enhanced_speed"] is not None:
                stream.speed_mps[idx] = float(rec["enhanced_speed"])
            # Prefer enhanced_altitude when available because it is the
            # higher-resolution FIT field used by modern head units. Fall back
            # to standard altitude for older files. Both are stored in the
            # canonical altitude_m array so existing code keeps working.
            if "enhanced_altitude" in rec and rec["enhanced_altitude"] is not None:
                stream.altitude_m[idx] = float(rec["enhanced_altitude"])
            elif "altitude" in rec and rec["altitude"] is not None:
                stream.altitude_m[idx] = float(rec["altitude"])
            if "distance" in rec and rec["distance"] is not None:
                stream.distance_m[idx] = float(rec["distance"])
            if "position_lat" in rec and rec["position_lat"] is not None:
                stream.lat[idx] = float(rec["position_lat"])
            if "position_long" in rec and rec["position_long"] is not None:
                stream.lon[idx] = float(rec["position_long"])
            if "temperature" in rec and rec["temperature"] is not None:
                stream.temperature_c[idx] = float(rec["temperature"])
                # Standard 'temperature' field is ambient (from head unit sensor).
                # Store it separately for thermal analysis.
                stream.ambient_temp[idx] = float(rec["temperature"])

            _copy_first_numeric_field(
                rec,
                ("respiration_rate", "respiratory_rate", "breathing_rate", "respiration"),
                stream.respiration_rate,
                idx,
                min_value=3.0,
                max_value=80.0,
            )
            
            # Body temperature sensor data can arrive as developer fields with
            # various names depending on the head unit and sensor firmware.
            # We check all known variants.
            for core_field in ("core_body_temperature", "CoreBodyTemp",
                               "core_temperature", "body_temperature",
                               "core_temp"):
                if core_field in rec and rec[core_field] is not None:
                    try:
                        v = float(rec[core_field])
                        if 30.0 <= v <= 45.0:  # physiological range check
                            stream.core_body_temp[idx] = v
                            stream.has_core_sensor = True
                    except (TypeError, ValueError):
                        pass
                    break
            
            for skin_field in ("skin_temperature", "skin_temp", "SkinTemp"):
                if skin_field in rec and rec[skin_field] is not None:
                    try:
                        v = float(rec[skin_field])
                        if 15.0 <= v <= 45.0:  # physiological range
                            stream.skin_temp[idx] = v
                            stream.has_core_sensor = True
                    except (TypeError, ValueError):
                        pass
                    break
            
            # FIT records may store balance as 'left_right_balance' (raw 0-255) or
            # 'left_pedal_smoothness'/'left_power_phase' from cycling dynamics.
            # Per spec convention: top bit (0x80) flags right-dominant when set,
            # remaining 7 bits give the percent. fitparse normalizes most cases
            # to a plain 0-100 number for the LEFT side; we accept that directly.
            if "left_right_balance" in rec and rec["left_right_balance"] is not None:
                lrb = rec["left_right_balance"]
                try:
                    # Some firmwares emit dicts {"value": int, "right": bool}
                    if isinstance(lrb, dict):
                        v: Any = lrb.get("value")
                        if v is not None:
                            stream.left_right_balance[idx] = float(v)
                    else:
                        v = float(lrb)
                        # If raw 0-255 with top-bit flag, mask and re-interpret
                        if v > 100:
                            v_int = int(v)
                            pct_right = v_int & 0x7F
                            # If top bit set, value is right-percent; else left-percent
                            if v_int & 0x80:
                                stream.left_right_balance[idx] = float(100 - pct_right)
                            else:
                                stream.left_right_balance[idx] = float(pct_right)
                        else:
                            # Already 0-100 (left side), use as-is
                            stream.left_right_balance[idx] = v
                except (TypeError, ValueError):
                    pass
            # Cycling dynamics and pedal efficiency. Field names differ between
            # head units and developer-data profiles; keep a broad alias list and
            # store scalar series for charting/reporting.
            _copy_first_numeric_field(
                rec,
                ("left_power_phase", "power_phase_left", "left_power_phase_start"),
                stream.left_power_phase,
                idx,
                min_value=0.0,
                max_value=360.0,
            )
            _copy_first_numeric_field(
                rec,
                ("right_power_phase", "power_phase_right", "right_power_phase_start"),
                stream.right_power_phase,
                idx,
                min_value=0.0,
                max_value=360.0,
            )
            _copy_first_numeric_field(
                rec,
                ("left_power_phase_peak", "power_phase_peak_left", "left_power_phase_peak_start"),
                stream.left_power_phase_peak,
                idx,
                min_value=0.0,
                max_value=360.0,
            )
            _copy_first_numeric_field(
                rec,
                ("right_power_phase_peak", "power_phase_peak_right", "right_power_phase_peak_start"),
                stream.right_power_phase_peak,
                idx,
                min_value=0.0,
                max_value=360.0,
            )
            _copy_first_numeric_field(
                rec,
                ("left_pco", "left_platform_center_offset", "platform_center_offset_left"),
                stream.left_pco,
                idx,
                min_value=-100.0,
                max_value=100.0,
            )
            _copy_first_numeric_field(
                rec,
                ("right_pco", "right_platform_center_offset", "platform_center_offset_right"),
                stream.right_pco,
                idx,
                min_value=-100.0,
                max_value=100.0,
            )
            _copy_first_numeric_field(
                rec,
                ("left_pedal_smoothness", "pedal_smoothness_left"),
                stream.left_pedal_smoothness,
                idx,
                min_value=0.0,
                max_value=100.0,
            )
            _copy_first_numeric_field(
                rec,
                ("right_pedal_smoothness", "pedal_smoothness_right"),
                stream.right_pedal_smoothness,
                idx,
                min_value=0.0,
                max_value=100.0,
            )
            _copy_first_numeric_field(
                rec,
                ("left_torque_effectiveness", "torque_effectiveness_left"),
                stream.left_torque_effectiveness,
                idx,
                min_value=0.0,
                max_value=100.0,
            )
            _copy_first_numeric_field(
                rec,
                ("right_torque_effectiveness", "torque_effectiveness_right"),
                stream.right_torque_effectiveness,
                idx,
                min_value=0.0,
                max_value=100.0,
            )

            # Standing/seated position: FIT may expose 'stand' event or a
            # cadence-position field. Normalise to 0=seated, 1=standing.
            for pf in ("cadence_position", "standing", "stance"):
                if pf in rec and rec[pf] is not None:
                    try:
                        raw = rec[pf]
                        v = 1.0 if (raw is True or str(raw).lower() in ("standing", "stand", "1")) else 0.0
                        stream.cadence_position[idx] = v
                        stream.has_cycling_dynamics = True
                    except (TypeError, ValueError):
                        pass
                    break

            # Set dynamics/respiration flags when the corresponding series got
            # any value at this record (cheap per-record OR; charts check these).
            if not np.isnan(stream.left_power_phase[idx]) or not np.isnan(stream.left_pco[idx]) \
                    or not np.isnan(stream.right_power_phase[idx]) or not np.isnan(stream.right_pco[idx]):
                stream.has_cycling_dynamics = True
            if not np.isnan(stream.respiration_rate[idx]):
                stream.has_respiration = True

            # RR intervals (HRV-capable devices): list of beat-to-beat ms values
            if rec.get("rr_intervals"):
                rrs = rec["rr_intervals"]
                if isinstance(rrs, (list, tuple)):
                    stream.rr_intervals[idx] = list(rrs)
                else:
                    stream.rr_intervals[idx] = [float(rrs)]
    
    # Detect and fill gaps
    power_filled, quality_p, gap_stats_p = detect_and_fill_gaps(
        stream.power, stream.quality_power, stream.elapsed_s,
        gap_short_s, gap_long_s,
        zero_is_missing=False,  # 0W = coasting, not a sensor dropout
    )
    hr_filled, quality_hr, gap_stats_hr = detect_and_fill_gaps(
        stream.heart_rate, stream.quality_hr, stream.elapsed_s,
        gap_short_s, gap_long_s,
        zero_is_missing=True,   # 0 bpm = sensor dropout
    )
    
    stream.power = power_filled
    stream.quality_power = quality_p
    stream.heart_rate = hr_filled
    stream.quality_hr = quality_hr
    
    stream.gap_summary = {
        "power": gap_stats_p,
        "heart_rate": gap_stats_hr,
    }
    
    return stream


if __name__ == "__main__":  # pragma: no cover
    # Self-test with synthetic data
    print("FIT Parser — Gap Handling Test")
    print("=" * 60)
    
    # Simulate sensor dropout
    n = 300
    power = np.full(n, 200.0)
    power[100:110] = 0  # 10s gap → interpolate
    power[150:180] = 0  # 30s gap → forward-fill
    power[250:280] = 0  # 30s gap → forward-fill
    
    quality = np.full(n, QUALITY_GOOD, dtype=np.uint8)
    elapsed = np.arange(n, dtype=np.float32)
    
    filled, qual, stats = detect_and_fill_gaps(power, quality, elapsed)
    
    print(f"Gaps detected: {stats['n_gaps']}")
    print(f"  Interpolated: {stats['interpolated']}")
    print(f"  Forward-filled: {stats['forward_filled']}")
    print(f"  Unreliable: {stats['unreliable']}")
    print()
    
    print("Sample filled values:")
    print(f"  Before gap [95:105]: {filled[95:105]}")
    print(f"  Quality [95:105]: {qual[95:105]}")
