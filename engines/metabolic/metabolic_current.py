"""
Metabolic Current — Integration Wrapper
Version: 1.0.0

Bridges detraining_engine with the rest of the Digital Twin backend.
Designed to be called from Supabase Edge Functions or Lambda handlers.

Input: athlete_id + workout_history (from Supabase)
Output: Current metabolic status (baseline + decayed)
"""

from typing import Dict, Any, List, Optional, Union
from datetime import date, datetime

from engines.core.metric_contracts import annotate_payload
from engines.core.model_safety import finalize_model_metadata

# Flat imports only — avoid `engines.*` or relative imports here, which
# re-enter `engines/__init__.py` while it is still initialising.
from engines.core.athlete_context import AthleteContext
from engines.metabolic.detraining_engine import apply_detraining_model
from engines.metabolic.metabolic_profiler import MetabolicProfiler


def get_current_metabolic_status(
    historical_mmp: Dict[int, float],
    workout_history: List[Dict[str, Any]],
    athlete_weight_kg: float,
    athlete_context: Optional[Dict[str, Any]] = None,
    today: Optional[Union[date, str]] = None,
) -> Dict[str, Any]:
    """
    Get current metabolic status with detraining decay applied.
    
    This is the main entry point for Edge Functions / Lambda handlers.
    
    Parameters:
        historical_mmp: Best efforts by duration (seconds → watts)
            Example: {30: 850, 60: 720, 180: 520, 300: 420, 600: 340, 1200: 290}
        
        workout_history: Recent workouts with TSS (last 90 days)
            Example: [{"date": "2026-04-01", "tss": 80}, ...]
            Accepts both ISO strings and date objects
        
        athlete_weight_kg: Current weight in kg
        
        athlete_context: Optional context (gender, training_years, discipline)
            Example: {"gender": "MALE", "training_years": 5, "discipline": "ROAD"}
            Defaults to generic male athlete if not provided
        
        today: Reference date (defaults to today)
            Accepts date object or ISO string
    
    Returns:
        Dict with:
        - baseline_* (peak metabolic values from MMP)
        - current_* (decayed values based on training load)
        - decay (% decay for each parameter)
        - training_load (CTL/ATL/TSB)
        - recommendations (actionable suggestions)
    """
    # Default today
    if today is None:
        today = date.today()
    elif isinstance(today, str):
        today = datetime.fromisoformat(today.split('T')[0]).date()
    
    # Normalize workout_history dates: docstring says we accept both ISO
    # strings and date objects, but detraining_engine compares them with
    # `<=`, which crashes on string-vs-date. Normalize to date objects here.
    normalized_history = []
    for entry in (workout_history or []):
        d = entry.get("date")
        if isinstance(d, str):
            try:
                d = datetime.fromisoformat(d.split('T')[0]).date()
            except ValueError:
                # Skip malformed dates rather than crash silently
                continue
        elif isinstance(d, datetime):
            d = d.date()
        elif not isinstance(d, date):
            # Unknown type — skip
            continue
        normalized_history.append({**entry, "date": d})
    workout_history = normalized_history
    
    # Create athlete context
    if athlete_context:
        ctx = AthleteContext(
            gender=athlete_context.get("gender", "MALE"),
            training_years=athlete_context.get("training_years", 3),
            discipline=athlete_context.get("discipline", "MIXED"),
            body_fat_pct=athlete_context.get("body_fat_pct"),
        )
    else:
        # Default context
        ctx = AthleteContext(gender="MALE", training_years=3, discipline="MIXED")
    
    # Generate baseline metabolic snapshot from historical MMP
    profiler = MetabolicProfiler(weight=athlete_weight_kg, context=ctx)
    baseline_snapshot = profiler.generate_metabolic_snapshot(historical_mmp)
    
    if baseline_snapshot.get("status") != "success":
        return annotate_payload({
            "status": "error",
            "error": "Failed to generate baseline metabolic snapshot",
            "details": baseline_snapshot,
            "model_metadata": finalize_model_metadata(
                assumptions=["baseline_snapshot_required_for_detraining_projection"],
                missing_inputs=["historical_mmp"],
                quality_flags=["baseline_generation_failed"],
                confidence=0.0,
            ),
        }, module_name="metabolic_current", method="mmp_detraining_current_status", confidence=0.0)
    
    # Apply detraining model
    current_status = apply_detraining_model(
        baseline_snapshot,
        workout_history,
        today,
    )
    
    if current_status.get("status") != "success":
        current_status["model_metadata"] = finalize_model_metadata(
            assumptions=["detraining_model_requires_valid_baseline_and_history"],
            missing_inputs=[],
            quality_flags=["detraining_failed"],
            confidence=0.0,
        )
        return annotate_payload(
            current_status,
            module_name="metabolic_current",
            method="mmp_detraining_current_status",
            confidence=0.0,
        )
    
    # Add metadata. We report the EFFECTIVE values (the ones actually used by
    # the model after resolution/defaulting), not the raw user input — so that
    # downstream consumers see a coherent picture between "this is what was
    # used" and the actual computation.
    current_status["athlete"] = {
        "weight_kg": athlete_weight_kg,
        "gender": ctx.effective_gender(),
        "training_years": ctx.effective_training_years(),
        "discipline": ctx.effective_discipline(),
        "inferred_fields": ctx.inferred_fields(),
    }
    
    current_status["baseline_snapshot"] = {
        "metabolic_phenotype": baseline_snapshot.get("metabolic_phenotype"),
        "confidence_score": baseline_snapshot.get("confidence_score"),
    }
    current_status["model_metadata"] = finalize_model_metadata(
        assumptions=["detraining_projection_is_model_based_not_diagnostic"],
        missing_inputs=[],
        quality_flags=[],
        confidence=min(
            float(baseline_snapshot.get("confidence_score") or 0.0),
            float((current_status.get("uncertainty") or {}).get("confidence_score") or 0.0),
        ),
    )
    
    return annotate_payload(
        current_status,
        module_name="metabolic_current",
        method="mmp_detraining_current_status",
        confidence=current_status.get("uncertainty", {}).get("confidence_score"),
        limitations=["Combines model-derived MMP estimates with heuristic detraining."],
    )


# =============================================================================
# SUPABASE EDGE FUNCTION ADAPTER
# =============================================================================

def handle_edge_function_request(request_body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Adapter for Supabase Edge Functions (TypeScript).
    
    Expected request body:
    {
      "athlete_id": "uuid",
      "historical_mmp": {30: 850, 60: 720, ...},
      "workout_history": [{"date": "2026-04-01", "tss": 80}, ...],
      "athlete_weight_kg": 75.0,
      "athlete_context": {"gender": "MALE", "training_years": 5, ...},
      "today": "2026-05-15"  // optional
    }
    
    Returns JSON response.
    """
    try:
        result = get_current_metabolic_status(
            historical_mmp=request_body["historical_mmp"],
            workout_history=request_body["workout_history"],
            athlete_weight_kg=request_body["athlete_weight_kg"],
            athlete_context=request_body.get("athlete_context"),
            today=request_body.get("today"),
        )
        return result
    
    except KeyError as e:
        return {
            "status": "error",
            "error": f"Missing required field: {e}",
        }
    except Exception:
        # Log internally but don't expose stack traces to the client
        import logging
        logging.getLogger("engines.metabolic_current").exception(
            "Unhandled error in handle_edge_function_request"
        )
        return {
            "status": "error",
            "error": "Internal processing error. Check server logs for details.",
        }


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

if __name__ == "__main__":  # pragma: no cover
    # Simulate Edge Function request
    request = {
        "athlete_id": "c226ee4e-9f9c-47fb-9cb5-4d5332d0220e",
        "historical_mmp": {
            30: 850,
            60: 720,
            180: 520,
            300: 420,
            600: 340,
            1200: 290,
        },
        "workout_history": [
            {"date": "2026-04-01", "tss": 80},
            {"date": "2026-04-03", "tss": 65},
            {"date": "2026-04-05", "tss": 90},
            {"date": "2026-04-08", "tss": 100},
            {"date": "2026-04-28", "tss": 75},
            # Then 17 days inactive
        ],
        "athlete_weight_kg": 75.0,
        "athlete_context": {
            "gender": "MALE",
            "training_years": 5,
            "discipline": "ROAD",
        },
        "today": "2026-05-15",
    }
    
    response = handle_edge_function_request(request)
    
    import json
    print("=" * 80)
    print("METABOLIC CURRENT — Edge Function Response")
    print("=" * 80)
    print(json.dumps(response, indent=2, default=str))
