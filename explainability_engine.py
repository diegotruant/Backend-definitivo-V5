"""
Explainability Engine — Confidence Scoring & Narrative Generation
Version: 1.0.0

Transforms complex analytics into understandable coaching narratives.

WHY THIS MATTERS:
Without explainability, Digital Twin is a "black box":
- Coach doesn't know why FTP changed
- Athlete doesn't trust durability score
- Hard to commercialize

With explainability:
- "VO2max: 67.8 ml/kg/min (95% confidence, based on 5 strong efforts)"
- "Durability weak because power dropped 18W/hour — increase Zone 2 volume"
- Transparent, trustworthy, actionable
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum


# =============================================================================
# CONFIDENCE LEVELS
# =============================================================================

class ConfidenceLevel(Enum):
    """Confidence classification for metrics"""
    VERY_LOW = "very_low"      # <50% - unreliable
    LOW = "low"                # 50-70% - caution
    MODERATE = "moderate"      # 70-85% - acceptable
    HIGH = "high"              # 85-95% - reliable
    VERY_HIGH = "very_high"    # >95% - excellent


@dataclass
class ConfidenceScore:
    """Confidence assessment for a metric"""
    metric_name: str
    value: float
    confidence_pct: float
    confidence_level: ConfidenceLevel
    factors: List[str]  # What influenced confidence
    limitations: List[str]  # Known issues


# =============================================================================
# CONFIDENCE CALCULATION
# =============================================================================

def calculate_vo2max_confidence(
    mmp_curve: Dict[int, float],
    efforts_count: int,
    data_quality_score: float,
) -> ConfidenceScore:
    """
    Calculate confidence for VO2max estimation.
    
    Factors:
    - Number of maximal efforts (5+ = high confidence)
    - Data quality (HR stability, no dropouts)
    - Effort duration coverage (30s to 20min)
    """
    confidence_pct = 50.0  # Base
    factors = []
    limitations = []
    
    # Factor 1: Efforts count
    if efforts_count >= 5:
        confidence_pct += 30
        factors.append(f"{efforts_count} maximal efforts (excellent coverage)")
    elif efforts_count >= 3:
        confidence_pct += 20
        factors.append(f"{efforts_count} efforts (good)")
    else:
        confidence_pct += 5
        limitations.append(f"Only {efforts_count} efforts (need 5+ for high confidence)")
    
    # Factor 2: Duration coverage
    durations = list(mmp_curve.keys())
    has_short = any(d < 120 for d in durations)  # <2min
    has_medium = any(120 <= d <= 600 for d in durations)  # 2-10min
    has_long = any(d > 600 for d in durations)  # >10min
    
    if has_short and has_medium and has_long:
        confidence_pct += 15
        factors.append("Full duration spectrum covered")
    elif has_medium:
        confidence_pct += 10
        factors.append("Medium durations covered")
    else:
        limitations.append("Missing key duration ranges")
    
    # Factor 3: Data quality
    if data_quality_score > 0.9:
        confidence_pct += 5
        factors.append("Clean data (no dropouts)")
    elif data_quality_score < 0.7:
        confidence_pct -= 10
        limitations.append("Data quality issues detected")
    
    # Classify confidence level
    if confidence_pct >= 95:
        level = ConfidenceLevel.VERY_HIGH
    elif confidence_pct >= 85:
        level = ConfidenceLevel.HIGH
    elif confidence_pct >= 70:
        level = ConfidenceLevel.MODERATE
    elif confidence_pct >= 50:
        level = ConfidenceLevel.LOW
    else:
        level = ConfidenceLevel.VERY_LOW
    
    return ConfidenceScore(
        metric_name="VO2max",
        value=confidence_pct,
        confidence_pct=confidence_pct,
        confidence_level=level,
        factors=factors,
        limitations=limitations,
    )


def calculate_durability_confidence(
    duration_hours: float,
    power_data_completeness: float,
) -> ConfidenceScore:
    """
    Confidence for durability index.
    
    Factors:
    - Ride duration (3+ hours = high confidence)
    - Power data completeness (no zeros/gaps)
    """
    confidence_pct = 60.0
    factors = []
    limitations = []
    
    # Duration factor
    if duration_hours >= 4:
        confidence_pct += 30
        factors.append(f"{duration_hours:.1f}h ride (excellent for durability)")
    elif duration_hours >= 3:
        confidence_pct += 20
        factors.append(f"{duration_hours:.1f}h ride (good)")
    elif duration_hours >= 2:
        confidence_pct += 10
        factors.append(f"{duration_hours:.1f}h ride (minimum)")
    else:
        limitations.append(f"{duration_hours:.1f}h too short (need 2+)")
    
    # Completeness factor
    if power_data_completeness > 0.95:
        confidence_pct += 10
        factors.append("Complete power data")
    elif power_data_completeness < 0.85:
        confidence_pct -= 15
        limitations.append("Power data gaps detected")
    
    # Classify
    if confidence_pct >= 95:
        level = ConfidenceLevel.VERY_HIGH
    elif confidence_pct >= 85:
        level = ConfidenceLevel.HIGH
    elif confidence_pct >= 70:
        level = ConfidenceLevel.MODERATE
    elif confidence_pct >= 50:
        level = ConfidenceLevel.LOW
    else:
        level = ConfidenceLevel.VERY_LOW
    
    return ConfidenceScore(
        metric_name="Durability Index",
        value=confidence_pct,
        confidence_pct=confidence_pct,
        confidence_level=level,
        factors=factors,
        limitations=limitations,
    )


# =============================================================================
# NARRATIVE GENERATION
# =============================================================================

def generate_metric_narrative(
    metric_name: str,
    value: float,
    confidence: ConfidenceScore,
    context: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Generate human-readable narrative for a metric.
    
    Example:
    "VO2max: 67.8 ml/kg/min (HIGH confidence)
     Based on 5 strong maximal efforts across full duration spectrum.
     This value is reliable for training prescription."
    """
    # Header
    confidence_emoji = {
        ConfidenceLevel.VERY_HIGH: "🟢",
        ConfidenceLevel.HIGH: "🟢",
        ConfidenceLevel.MODERATE: "🟡",
        ConfidenceLevel.LOW: "🟠",
        ConfidenceLevel.VERY_LOW: "🔴",
    }
    
    emoji = confidence_emoji[confidence.confidence_level]
    
    narrative = f"{emoji} {metric_name}: {value:.1f}"
    
    # Confidence statement
    conf_text = confidence.confidence_level.name.replace('_', ' ').title()
    narrative += f"\n   Confidence: {conf_text} ({confidence.confidence_pct:.0f}%)"
    
    # Factors
    if confidence.factors:
        narrative += "\n   Why: " + "; ".join(confidence.factors)
    
    # Limitations
    if confidence.limitations:
        narrative += "\n   ⚠️  Note: " + "; ".join(confidence.limitations)
    
    # Recommendation
    if confidence.confidence_level in [ConfidenceLevel.VERY_LOW, ConfidenceLevel.LOW]:
        narrative += "\n   💡 Improve: Perform more maximal efforts to increase reliability"
    
    return narrative


def generate_durability_narrative(
    durability_index: float,
    classification: str,
    confidence: ConfidenceScore,
    prescription: Dict[str, Any],
) -> str:
    """
    Full coaching narrative for durability.
    
    Example:
    "Your durability is GOOD (93.7%) — power dropped only 16W over 3 hours.
     This indicates a solid aerobic base with room for fine-tuning.
     
     What this means:
     - You maintain power well on long rides
     - Minor fatigue resistance weakness
     
     How to improve:
     - Increase Zone 2 volume to 75-85%
     - Focus on 2-3h base rides 3x/week
     - Reduce high-intensity work temporarily
     
     Expected improvement: 93.7% → 96%+ in 4-6 weeks"
    """
    # Assessment
    narrative = f"**Durability Assessment**: {classification} ({durability_index:.1f}%)\n\n"
    
    # Interpretation
    if classification == "EXCELLENT":
        narrative += "Elite-level durability — you maintain power exceptionally well over long efforts.\n"
    elif classification == "GOOD":
        narrative += "Solid aerobic base with minor decay — good endurance foundation.\n"
    elif classification == "FAIR":
        narrative += "Moderate durability — significant room for aerobic base improvement.\n"
    else:  # POOR
        narrative += "Low durability — aerobic base needs urgent attention.\n"
    
    narrative += "\n"
    
    # Confidence
    conf_emoji = "🟢" if confidence.confidence_pct > 85 else "🟡"
    narrative += f"{conf_emoji} **Confidence**: {confidence.confidence_level.name.replace('_', ' ').title()}\n"
    narrative += f"   Based on: {'; '.join(confidence.factors)}\n\n"
    
    # Prescription
    narrative += "**Training Recommendations**:\n"
    narrative += f"   Focus: {prescription['focus']}\n"
    narrative += f"   Volume: {prescription['volume']}\n"
    narrative += "   Key Sessions:\n"
    for session in prescription['key_sessions']:
        narrative += f"   • {session}\n"
    
    return narrative


def generate_acwr_narrative(
    acwr_value: float,
    risk_level: str,
    ctl: float,
    atl: float,
    tsb: float,
) -> str:
    """
    Injury risk narrative.
    
    Example:
    "⚠️ WARNING: High Injury Risk Detected
     
     Your ACWR is 1.52 — significantly above safe zone (0.8-1.3).
     This means recent training load is 52% higher than your chronic baseline.
     
     What this means:
     - 2-4× increased injury risk
     - Overtraining symptoms likely
     - Need immediate load reduction
     
     Action required:
     1. Reduce this week's TSS by 30-40%
     2. Add extra rest day
     3. Monitor HRV closely
     4. No high-intensity work
     
     Target: Get ACWR back to 0.8-1.3 within 7 days"
    """
    if risk_level == "HIGH":
        emoji = "🔴"
        severity = "WARNING: High Injury Risk"
    elif risk_level == "MODERATE":
        emoji = "🟡"
        severity = "CAUTION: Moderate Risk"
    else:
        emoji = "🟢"
        severity = "Optimal Training Load"
    
    narrative = f"{emoji} **{severity}**\n\n"
    narrative += f"ACWR: {acwr_value:.2f}\n"
    narrative += f"Acute Load (ATL): {atl:.0f}\n"
    narrative += f"Chronic Load (CTL): {ctl:.0f}\n"
    narrative += f"Training Stress Balance (TSB): {tsb:.0f}\n\n"
    
    # Interpretation
    if risk_level == "HIGH":
        pct_above = ((acwr_value / 1.3) - 1) * 100
        narrative += f"⚠️ You're {pct_above:.0f}% above safe zone (1.3 limit)\n"
        narrative += f"Research shows 2-4× increased injury risk at this level\n\n"
        narrative += "**Action Required**:\n"
        narrative += "1. Reduce training load by 30-40% this week\n"
        narrative += "2. Add extra rest day\n"
        narrative += "3. Monitor HRV/sleep closely\n"
        narrative += "4. No threshold or VO2max work\n\n"
        narrative += "Target: ACWR < 1.3 within 7 days"
    
    elif risk_level == "MODERATE":
        narrative += "Approaching high load — monitor closely\n"
        narrative += "Consider: easier week, extra recovery\n"
    
    else:  # OPTIMAL
        narrative += "✅ Good acute:chronic balance\n"
        narrative += "Training load is sustainable\n"
    
    return narrative


# =============================================================================
# COMPREHENSIVE SUMMARY GENERATOR
# =============================================================================

def generate_workout_summary_narrative(
    workout_summary: Dict[str, Any],
) -> str:
    """
    Master narrative generator — synthesizes entire workout.
    
    Transforms complex JSON into coaching language:
    "3-hour endurance ride showing GOOD durability (93.7%).
     Metabolic profile: VO2max 67.8 (HIGH confidence).
     Power well-maintained — only 16W decay.
     Training advice: continue current base volume."
    """
    headline = workout_summary['headline']
    sections = workout_summary['sections']
    
    # Header
    narrative = f"**{headline['workout_type']} Workout**\n"
    narrative += f"Duration: {headline['duration_formatted']} | TSS: {headline['tss']:.0f} | IF: {headline['if_value']:.2f}\n\n"
    
    # Durability (if available)
    if sections.get('durability') and sections['durability'].get('status') == 'success':
        dur = sections['durability']['metrics']['durability_index']
        narrative += f"**Durability**: {dur['classification']} ({dur['value']:.1f}%)\n"
        narrative += f"   Power decay: {dur['decay_watts']:.0f}W over {dur['first_hour_avg']:.0f}W → {dur['last_hour_avg']:.0f}W\n"
        narrative += f"   {dur['interpretation']}\n\n"
    
    # Metabolic
    if sections.get('power', {}).get('metabolic_snapshot'):
        meta = sections['power']['metabolic_snapshot']
        narrative += f"**Metabolic Profile**:\n"
        narrative += f"   VO2max: {meta['vo2max_ml_kg_min']:.1f} ml/kg/min\n"
        narrative += f"   VLamax: {meta['vlamax_mmol_l_s']:.2f} mmol/L/s\n"
        narrative += f"   MLSS: {meta['mlss_power_watts']:.0f}W\n\n"
    
    # HRV insights
    if sections.get('hrv', {}).get('vt1_detected'):
        hrv = sections['hrv']
        narrative += f"**HRV Insights**:\n"
        narrative += f"   VT1 detected at {hrv['vt1_power']:.0f}W (aerobic threshold)\n\n"
    
    # Recommendation
    narrative += "**Next Steps**: [Coach prescription based on results]\n"
    
    return narrative


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

if __name__ == "__main__":
    # Example 1: VO2max confidence
    mmp = {30: 850, 60: 720, 180: 520, 300: 420, 1200: 290}
    vo2max_conf = calculate_vo2max_confidence(
        mmp_curve=mmp,
        efforts_count=5,
        data_quality_score=0.95,
    )
    
    print("=" * 80)
    print(generate_metric_narrative(
        metric_name="VO2max",
        value=67.8,
        confidence=vo2max_conf,
    ))
    
    # Example 2: Durability narrative
    print("\n" + "=" * 80)
    dur_conf = calculate_durability_confidence(
        duration_hours=3.2,
        power_data_completeness=0.97,
    )
    
    prescription = {
        "focus": "Fine-tune aerobic efficiency",
        "volume": "75-85% Zone 2, 10-15% Zone 3-4",
        "key_sessions": [
            "2-3h base rides 3x/week",
            "1x tempo intervals",
            "Optional: 1x VO2max work"
        ]
    }
    
    print(generate_durability_narrative(
        durability_index=93.7,
        classification="GOOD",
        confidence=dur_conf,
        prescription=prescription,
    ))
    
    # Example 3: ACWR warning
    print("\n" + "=" * 80)
    print(generate_acwr_narrative(
        acwr_value=1.52,
        risk_level="HIGH",
        ctl=62.0,
        atl=94.0,
        tsb=-32.0,
    ))
