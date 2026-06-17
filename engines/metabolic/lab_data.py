"""
Lab Data Ingestion
===================

Universal intake for laboratory test results from any source worldwide.
Normalizes heterogeneous inputs (manual entry, PDF reports, JSON API)
into a standard `LabTestResult` that the Kalman filter can consume
as a high-confidence observation.

Supported source categories (extensible)
----------------------------------------
- Direct spirometry systems
- Metabolic profiling platforms
- Blood lactate analyzers
- Muscle oxygen sensors

The module does NOT need to know which device produced the data —
it normalizes whatever values are provided into the standard format.
Unknown sources are accepted; the coach simply enters the values.

Architecture
------------
Three input paths, one output:

  1. `create_lab_result(**kwargs)` — manual entry (always works)
  2. `parse_lab_pdf(filepath)` — extract values from PDF reports
  3. `LabTestResult.from_dict(d)` — programmatic / API integration

All paths produce a `LabTestResult` which feeds into:
  `MetabolicKalman.update_from_lab(lab_result)`

The Kalman treats lab observations with very low measurement noise
(R ≈ 1.0 for VO2max vs R ≈ 225 for MMP-based estimates), so a single
lab test anchors the state estimate far more than dozens of field tests.

Tier: REFERENCE (data normalization) + MODEL (Kalman integration)
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from datetime import date
from enum import Enum
import re


# =============================================================================
# Source classification
# =============================================================================

class LabSource(Enum):
    """Known lab data sources. UNKNOWN is always valid."""
    SPIROMETRY = "spirometry"
    METABOLIC_PROFILE = "metabolic_profile"
    LACTATE_ANALYZER = "lactate_analyzer"
    MUSCLE_OXYGEN = "muscle_oxygen"
    
    # Generic / manual
    UNKNOWN = "unknown"
    MANUAL = "manual_entry"
    OTHER_LAB = "other_lab"


class LabTestType(Enum):
    """Type of test performed."""
    RAMP_SPIROMETRY = "ramp_spirometry"           # incremental ramp with gas exchange
    STEP_SPIROMETRY = "step_spirometry"            # step protocol with gas exchange
    LACTATE_STEP = "lactate_step"                  # incremental steps with blood draws
    LACTATE_RAMP = "lactate_ramp"                  # ramp with blood draws
    METABOLIC_PROFILE = "metabolic_profile"
    FIELD_TEST_LAB_SUPERVISED = "field_test_lab"   # field test with lab supervision
    VO2MAX_ONLY = "vo2max_only"                    # only VO2max measured
    UNKNOWN = "unknown"


# =============================================================================
# Lactate curve data point
# =============================================================================

@dataclass
class LactatePoint:
    """One blood lactate measurement at a given intensity."""
    power_w: Optional[float] = None       # watts at this step
    heart_rate_bpm: Optional[float] = None
    lactate_mmol: float = 0.0              # blood lactate (mmol/L)
    vo2_ml_kg_min: Optional[float] = None  # if spirometry was concurrent
    duration_s: Optional[int] = None       # step duration
    rpe: Optional[int] = None              # rate of perceived exertion (6-20 Borg)
    
    def to_dict(self) -> Dict[str, Any]:
        d = {}
        for k, v in self.__dict__.items():
            if v is not None:
                d[k] = v
        return d


# =============================================================================
# Normalized lab test result
# =============================================================================

@dataclass
class LabTestResult:
    """
    Universal container for lab test data.
    
    Not all fields will be populated — it depends on what was measured.
    The system uses whatever is available: even a single VO2max value
    from spirometry is a powerful anchor for the Kalman filter.
    
    All values should be in standard units:
      - VO2: ml/kg/min
      - Power: watts
      - Lactate: mmol/L
      - VLamax: mmol/L/s
      - Heart rate: bpm
      - Temperature: °C
      - Weight: kg
    """
    # ── Metadata ──
    test_date: date
    source: LabSource = LabSource.UNKNOWN
    test_type: LabTestType = LabTestType.UNKNOWN
    source_label: str = ""                    # free text: "Spirometry system @ Lab XYZ"
    athlete_weight_kg: Optional[float] = None # weight at time of test
    altitude_m: Optional[float] = None        # lab altitude (for hypoxia correction)
    ambient_temp_c: Optional[float] = None    # lab temperature
    notes: str = ""
    
    # ── Primary metabolic parameters ──
    vo2max_ml_kg_min: Optional[float] = None  # from spirometry (gold standard)
    vo2max_absolute_ml_min: Optional[float] = None  # absolute VO2max
    vlamax_mmol_L_s: Optional[float] = None   # from metabolic profiling
    
    # ── Threshold markers ──
    lt1_power_w: Optional[float] = None       # lactate threshold 1 (aerobic threshold)
    lt1_hr_bpm: Optional[float] = None
    lt1_vo2_ml_kg: Optional[float] = None
    lt1_lactate_mmol: Optional[float] = None  # typically ~2 mmol/L
    
    lt2_power_w: Optional[float] = None       # lactate threshold 2 (MLSS/OBLA)
    lt2_hr_bpm: Optional[float] = None
    lt2_vo2_ml_kg: Optional[float] = None
    lt2_lactate_mmol: Optional[float] = None  # typically ~4 mmol/L
    
    mlss_power_w: Optional[float] = None      # maximal lactate steady state
    
    # ── Fat metabolism ──
    fatmax_power_w: Optional[float] = None    # power at peak fat oxidation
    fatmax_fat_g_min: Optional[float] = None  # peak fat oxidation rate
    fat_ox_at_lt1_g_min: Optional[float] = None
    
    # ── Performance markers ──
    map_w: Optional[float] = None             # maximal aerobic power (peak ramp)
    hr_max_bpm: Optional[float] = None
    rpe_max: Optional[int] = None
    rer_max: Optional[float] = None           # respiratory exchange ratio at max
    
    # ── Economy / efficiency ──
    gross_efficiency_pct: Optional[float] = None  # mechanical efficiency
    economy_w_per_l_o2: Optional[float] = None
    
    # ── Lactate curve ──
    lactate_curve: Optional[List[LactatePoint]] = None
    
    # ── Body composition (if measured) ──
    body_fat_pct: Optional[float] = None
    lean_mass_kg: Optional[float] = None
    
    # ── Quality / confidence ──
    is_maximal_test: Optional[bool] = None    # did the athlete reach VO2max criteria?
    rer_plateau_reached: Optional[bool] = None
    data_quality: str = "good"                # "good" | "partial" | "suspect"
    
    # ── Measurement noise estimates ──
    # These inform the Kalman R matrix — how much to trust this observation
    vo2max_noise_ml_kg: float = 1.0           # spirometry: ±1 ml/kg/min typical
    vlamax_noise_mmol: float = 0.03           # metabolic profiling: ±0.03 typical
    power_noise_w: float = 3.0                # lab ergometer: ±3W typical
    
    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"tier": "REFERENCE"}
        for k, v in self.__dict__.items():
            if v is None:
                continue
            if isinstance(v, (LabSource, LabTestType)):
                d[k] = v.value
            elif isinstance(v, date):
                d[k] = v.isoformat()
            elif isinstance(v, list):
                d[k] = [item.to_dict() if hasattr(item, "to_dict") else item for item in v]
            else:
                d[k] = v
        return d
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "LabTestResult":
        """Create from a dictionary (API / JSON import)."""
        # Parse date
        test_date = d.get("test_date")
        if isinstance(test_date, str):
            test_date = date.fromisoformat(test_date)
        elif test_date is None:
            test_date = date.today()
        
        # Parse source
        source = d.get("source", "unknown")
        if isinstance(source, str):
            try:
                source = LabSource(source)
            except ValueError:
                source = LabSource.UNKNOWN
        
        # Parse test type
        test_type = d.get("test_type", "unknown")
        if isinstance(test_type, str):
            try:
                test_type = LabTestType(test_type)
            except ValueError:
                test_type = LabTestType.UNKNOWN
        
        # Parse lactate curve
        lactate_curve = None
        if "lactate_curve" in d and d["lactate_curve"]:
            lactate_curve = [
                LactatePoint(**pt) if isinstance(pt, dict) else pt
                for pt in d["lactate_curve"]
            ]
        
        return cls(
            test_date=test_date,
            source=source,
            test_type=test_type,
            source_label=d.get("source_label", ""),
            athlete_weight_kg=d.get("athlete_weight_kg"),
            altitude_m=d.get("altitude_m"),
            ambient_temp_c=d.get("ambient_temp_c"),
            notes=d.get("notes", ""),
            vo2max_ml_kg_min=d.get("vo2max_ml_kg_min"),
            vo2max_absolute_ml_min=d.get("vo2max_absolute_ml_min"),
            vlamax_mmol_L_s=d.get("vlamax_mmol_L_s"),
            lt1_power_w=d.get("lt1_power_w"),
            lt1_hr_bpm=d.get("lt1_hr_bpm"),
            lt1_vo2_ml_kg=d.get("lt1_vo2_ml_kg"),
            lt1_lactate_mmol=d.get("lt1_lactate_mmol"),
            lt2_power_w=d.get("lt2_power_w"),
            lt2_hr_bpm=d.get("lt2_hr_bpm"),
            lt2_vo2_ml_kg=d.get("lt2_vo2_ml_kg"),
            lt2_lactate_mmol=d.get("lt2_lactate_mmol"),
            mlss_power_w=d.get("mlss_power_w"),
            fatmax_power_w=d.get("fatmax_power_w"),
            fatmax_fat_g_min=d.get("fatmax_fat_g_min"),
            map_w=d.get("map_w"),
            hr_max_bpm=d.get("hr_max_bpm"),
            rer_max=d.get("rer_max"),
            gross_efficiency_pct=d.get("gross_efficiency_pct"),
            economy_w_per_l_o2=d.get("economy_w_per_l_o2"),
            lactate_curve=lactate_curve,
            body_fat_pct=d.get("body_fat_pct"),
            lean_mass_kg=d.get("lean_mass_kg"),
            is_maximal_test=d.get("is_maximal_test"),
            data_quality=d.get("data_quality", "good"),
            vo2max_noise_ml_kg=d.get("vo2max_noise_ml_kg", 1.0),
            vlamax_noise_mmol=d.get("vlamax_noise_mmol", 0.03),
            power_noise_w=d.get("power_noise_w", 3.0),
        )
    
    @property
    def has_vo2max(self) -> bool:
        return self.vo2max_ml_kg_min is not None
    
    @property
    def has_vlamax(self) -> bool:
        return self.vlamax_mmol_L_s is not None
    
    @property
    def has_lactate_curve(self) -> bool:
        return self.lactate_curve is not None and len(self.lactate_curve) >= 3
    
    @property
    def has_thresholds(self) -> bool:
        return self.lt2_power_w is not None or self.mlss_power_w is not None
    
    @property
    def n_parameters_available(self) -> int:
        """Count how many primary parameters are available."""
        count = 0
        for attr in ("vo2max_ml_kg_min", "vlamax_mmol_L_s", "lt1_power_w",
                      "lt2_power_w", "mlss_power_w", "fatmax_power_w",
                      "map_w", "hr_max_bpm", "gross_efficiency_pct"):
            if getattr(self, attr) is not None:
                count += 1
        return count
    
    def summary(self) -> str:
        """Human-readable summary for the coach."""
        parts = [f"Lab test: {self.test_date.isoformat()}"]
        if self.source_label:
            parts[0] += f" ({self.source_label})"
        elif self.source != LabSource.UNKNOWN:
            parts[0] += f" ({self.source.value})"
        
        if self.has_vo2max:
            parts.append(f"VO₂max: {self.vo2max_ml_kg_min:.1f} ml/kg/min")
        if self.has_vlamax:
            parts.append(f"VLamax: {self.vlamax_mmol_L_s:.3f} mmol/L/s")
        if self.mlss_power_w:
            parts.append(f"MLSS: {self.mlss_power_w:.0f} W")
        if self.lt2_power_w:
            parts.append(f"LT2: {self.lt2_power_w:.0f} W")
        if self.fatmax_power_w:
            parts.append(f"FatMax: {self.fatmax_power_w:.0f} W")
        if self.map_w:
            parts.append(f"MAP: {self.map_w:.0f} W")
        if self.has_lactate_curve:
            curve = self.lactate_curve or []
            parts.append(f"Lactate curve: {len(curve)} points")
        
        return " | ".join(parts)


# =============================================================================
# Manual entry helper (the most universal input method)
# =============================================================================

def create_lab_result(
    test_date: date,
    source: str = "manual_entry",
    source_label: str = "",
    # Primary — at least one of these should be provided
    vo2max: Optional[float] = None,
    vlamax: Optional[float] = None,
    mlss_w: Optional[float] = None,
    ftp_w: Optional[float] = None,
    fatmax_w: Optional[float] = None,
    map_w: Optional[float] = None,
    # Thresholds
    lt1_w: Optional[float] = None,
    lt2_w: Optional[float] = None,
    lt1_hr: Optional[float] = None,
    lt2_hr: Optional[float] = None,
    # Heart rate
    hr_max: Optional[float] = None,
    # Lactate curve: list of (watts, mmol/L) tuples
    lactate_curve: Optional[List[Tuple[float, float]]] = None,
    # Context
    weight_kg: Optional[float] = None,
    altitude_m: Optional[float] = None,
    notes: str = "",
    **kwargs,
) -> LabTestResult:
    """
    Create a LabTestResult from manual entry.
    
    This is the simplest path — the coach types values from a lab report.
    Any combination of parameters is accepted; the system uses whatever
    is available.
    
    Examples
    --------
    # Only VO2max from spirometry
    result = create_lab_result(
        test_date=date(2026, 5, 20),
        source="spirometry",
        vo2max=62.3,
        map_w=380,
    )
    
    # Metabolic profile report
    result = create_lab_result(
        test_date=date(2026, 5, 20),
        source="metabolic_profile",
        vo2max=58.5,
        vlamax=0.42,
        mlss_w=275,
        fatmax_w=175,
    )
    
    # Lactate step test
    result = create_lab_result(
        test_date=date(2026, 5, 20),
        source="lactate_analyzer",
        lactate_curve=[(150, 0.9), (180, 1.1), (210, 1.5), (240, 2.3),
                       (270, 3.8), (300, 5.5), (330, 8.2)],
        lt2_w=265,
        hr_max=185,
    )
    """
    # Parse source
    try:
        lab_source = LabSource(source)
    except ValueError:
        lab_source = LabSource.OTHER_LAB
    
    # Determine test type heuristically
    test_type = LabTestType.UNKNOWN
    if vo2max is not None and lactate_curve:
        test_type = LabTestType.STEP_SPIROMETRY
    elif vo2max is not None:
        test_type = LabTestType.VO2MAX_ONLY
    elif lactate_curve:
        test_type = LabTestType.LACTATE_STEP
    elif lab_source == LabSource.METABOLIC_PROFILE:
        test_type = LabTestType.METABOLIC_PROFILE
    
    # Parse lactate curve
    lc = None
    if lactate_curve:
        lc = [LactatePoint(power_w=w, lactate_mmol=lac) for w, lac in lactate_curve]
    
    # FTP → MLSS fallback
    if mlss_w is None and ftp_w is not None:
        mlss_w = ftp_w
    
    return LabTestResult(
        test_date=test_date,
        source=lab_source,
        test_type=test_type,
        source_label=source_label,
        athlete_weight_kg=weight_kg,
        altitude_m=altitude_m,
        notes=notes,
        vo2max_ml_kg_min=vo2max,
        vlamax_mmol_L_s=vlamax,
        lt1_power_w=lt1_w,
        lt1_hr_bpm=lt1_hr,
        lt2_power_w=lt2_w,
        lt2_hr_bpm=lt2_hr,
        mlss_power_w=mlss_w,
        fatmax_power_w=fatmax_w,
        map_w=map_w,
        hr_max_bpm=hr_max,
        lactate_curve=lc,
        **kwargs,
    )


# =============================================================================
# PDF parsing — extract key values from lab report PDFs
# =============================================================================

# Known patterns for extracting values from PDF text
_PATTERNS = {
    "vo2max": [
        r"VO2\s*max\s*(?:\(?\s*(?:rel(?:ative)?\.?|abs(?:olute)?\.?)\s*\)?)?\s*[:\s=]+\s*([\d.]+)\s*(?:ml|mL)",
        r"VO2\s*max\s*[:\s=]+\s*([\d.]+)",
        r"[Cc]onsumo\s+(?:di\s+)?O2\s*(?:massimo)?\s*[:\s=]+\s*([\d.]+)",
        r"VO2\s*peak\s*[:\s=]+\s*([\d.]+)",
    ],
    "vlamax": [
        r"VLa\s*max\s*[:\s=]+\s*([\d.]+)",
        r"VLamax\s*[:\s=]+\s*([\d.]+)\s*(?:mmol|mMol)",
    ],
    "mlss": [
        r"MLSS\s*[:\s=]+\s*([\d.]+)\s*(?:W|watt)",
        r"(?:soglia|threshold)\s+(?:anaerobica|anaerobic)?\s*[:\s=]+\s*([\d.]+)\s*W",
    ],
    "ftp": [
        r"FTP\s*[:\s=]+\s*([\d.]+)\s*(?:W|watt)",
    ],
    "fatmax": [
        r"Fat\s*Max\s*[:\s=]+\s*([\d.]+)\s*(?:W|watt)",
        r"Fat\s*(?:oxidation\s+)?peak\s*[:\s=]+\s*([\d.]+)",
    ],
    "map": [
        r"MAP\s*[:\s=]+\s*([\d.]+)\s*(?:W|watt)",
        r"(?:Potenza|Power)\s+(?:aerobica\s+)?(?:massima|max)\s*[:\s=]+\s*([\d.]+)",
    ],
    "hrmax": [
        r"(?:FC|HR)\s*max\s*[:\s=]+\s*(\d+)",
        r"(?:Frequenza|Heart)\s+(?:cardiaca\s+)?(?:massima|max)\s*[:\s=]+\s*(\d+)",
    ],
    "lt2": [
        r"(?:LT2|OBLA|soglia\s+2)\s*[:\s=]+\s*([\d.]+)\s*(?:W|watt)",
    ],
    "weight": [
        r"(?:Peso|Weight|Massa)\s*(?:corporeo|body)?\s*[:\s=]+\s*([\d.]+)\s*(?:kg)",
    ],
}

# Source detection from PDF text
_SOURCE_MARKERS = {
    LabSource.SPIROMETRY: ["spirometry", "gas exchange", "cpet", "vo2"],
    LabSource.METABOLIC_PROFILE: ["metabolic profile", "vlamax", "glycolytic"],
    LabSource.LACTATE_ANALYZER: ["lactate", "blood lactate"],
    LabSource.MUSCLE_OXYGEN: ["muscle oxygen", "sm02", "smo2"],
}


def parse_lab_text(text: str, test_date: Optional[date] = None) -> LabTestResult:
    """
    Extract lab values from raw text (e.g. from a PDF).
    
    Uses regex patterns to find known value formats. Works across
    languages (Italian, English, German patterns included).
    
    Parameters
    ----------
    text : str
        Raw text extracted from a lab report PDF.
    test_date : date, optional
        If not found in the text, uses this date.
    
    Returns
    -------
    LabTestResult with whatever values could be extracted.
    """
    text_lower = text.lower()
    
    # Detect source
    source = LabSource.UNKNOWN
    source_label = ""
    for src, markers in _SOURCE_MARKERS.items():
        if any(m in text_lower for m in markers):
            source = src
            source_label = src.value
            break
    
    # Extract values
    def find_first(patterns):
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                try:
                    return float(m.group(1))
                except (ValueError, IndexError):
                    continue
        return None
    
    vo2max = find_first(_PATTERNS["vo2max"])
    vlamax = find_first(_PATTERNS["vlamax"])
    mlss = find_first(_PATTERNS["mlss"])
    ftp = find_first(_PATTERNS["ftp"])
    fatmax = find_first(_PATTERNS["fatmax"])
    map_w = find_first(_PATTERNS["map"])
    hrmax = find_first(_PATTERNS["hrmax"])
    lt2 = find_first(_PATTERNS["lt2"])
    weight = find_first(_PATTERNS["weight"])
    
    # Try to find date in text
    if test_date is None:
        date_match = re.search(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](20\d{2})", text)
        if date_match:
            try:
                d, m, y = int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3))
                if d > 12:
                    test_date = date(y, m, d)
                else:
                    test_date = date(y, m, d)
            except ValueError:
                pass
        if test_date is None:
            test_date = date.today()
    
    return LabTestResult(
        test_date=test_date,
        source=source,
        source_label=source_label,
        test_type=LabTestType.METABOLIC_PROFILE if source == LabSource.METABOLIC_PROFILE
                  else LabTestType.VO2MAX_ONLY if vo2max else LabTestType.UNKNOWN,
        vo2max_ml_kg_min=vo2max,
        vlamax_mmol_L_s=vlamax,
        mlss_power_w=mlss or ftp,
        fatmax_power_w=fatmax,
        map_w=map_w,
        hr_max_bpm=hrmax,
        lt2_power_w=lt2,
        athlete_weight_kg=weight,
        data_quality="good" if vo2max or vlamax else "partial",
        notes=f"Auto-parsed from {source.value} report" if source != LabSource.UNKNOWN
              else "Auto-parsed from unknown report format",
    )


def parse_lab_pdf(filepath: str, test_date: Optional[date] = None) -> LabTestResult:
    """
    Extract lab values from a PDF file.
    
    Attempts text extraction with multiple methods:
    1. pypdf (pure Python, no external dependencies)
    2. Falls back to basic binary text search
    
    Parameters
    ----------
    filepath : str
        Path to the PDF file.
    test_date : date, optional
        Override the test date.
    
    Returns
    -------
    LabTestResult
    """
    text = ""
    
    # Try pypdf first
    try:
        from pypdf import PdfReader
        reader = PdfReader(filepath)
        for page in reader.pages:
            text += page.extract_text() or ""
    except ImportError:
        pass
    except Exception:
        pass
    
    # Fallback: try PyPDF2
    if not text:
        try:
            import PyPDF2
            with open(filepath, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    text += page.extract_text() or ""
        except (ImportError, Exception):
            pass
    
    # Last resort: read raw bytes and extract ASCII strings
    if not text:
        try:
            with open(filepath, "rb") as f:
                raw = f.read()
            # Extract printable ASCII sequences
            text = re.sub(rb'[^\x20-\x7E\n]', b' ', raw).decode('ascii', errors='ignore')
        except Exception:
            pass
    
    if not text.strip():
        return LabTestResult(
            test_date=test_date or date.today(),
            source=LabSource.UNKNOWN,
            data_quality="suspect",
            notes="Could not extract text from PDF",
        )
    
    result = parse_lab_text(text, test_date)
    result.notes += f" (extracted from: {filepath.split('/')[-1]})"
    return result


# =============================================================================
# Validation helpers
# =============================================================================

def validate_lab_result(result: LabTestResult) -> List[str]:
    """
    Check a lab result for suspicious values.
    Returns a list of warnings (empty = all good).
    """
    warnings = []
    
    if result.vo2max_ml_kg_min is not None:
        if result.vo2max_ml_kg_min < 15:
            warnings.append(f"VO2max {result.vo2max_ml_kg_min} ml/kg/min is extremely low — check units")
        if result.vo2max_ml_kg_min > 95:
            warnings.append(f"VO2max {result.vo2max_ml_kg_min} ml/kg/min exceeds world-class threshold — check units")
    
    if result.vlamax_mmol_L_s is not None:
        if result.vlamax_mmol_L_s < 0.05:
            warnings.append(f"VLamax {result.vlamax_mmol_L_s} is extremely low — check units")
        if result.vlamax_mmol_L_s > 2.0:
            warnings.append(f"VLamax {result.vlamax_mmol_L_s} exceeds physiological range")
    
    if result.mlss_power_w is not None and result.map_w is not None:
        if result.mlss_power_w > result.map_w:
            warnings.append("MLSS > MAP — check values (MLSS should be ~70-85% of MAP)")
    
    if result.hr_max_bpm is not None:
        if result.hr_max_bpm < 120:
            warnings.append(f"HRmax {result.hr_max_bpm} bpm seems too low — was this a maximal test?")
    
    if result.lactate_curve:
        lacs = [p.lactate_mmol for p in result.lactate_curve]
        if lacs != sorted(lacs):
            warnings.append("Lactate values are not monotonically increasing — check data order")
        if max(lacs) < 4.0:
            warnings.append("Peak lactate < 4 mmol/L — test may not have reached OBLA")
    
    if result.n_parameters_available == 0:
        warnings.append("No primary parameters extracted — check the report format")
    
    return warnings
