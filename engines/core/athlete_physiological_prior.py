"""
Athlete physiological prior manager.
====================================

Ties together three pieces that already exist in the backend but were not
connected:

  1. A *measured* physiological profile (e.g. a lab metabolic test, or a
     structured field test) -> the strong prior.
  2. The Bayesian profiler (bayesian_profiler.bayesian_metabolic_snapshot)
     -> the inference engine that combines prior + new ride data.
  3. The passage of time and the training load (CTL/ATL from Layer 1)
     -> how much the prior should be *trusted* now vs. how much fresh ride
     data should be allowed to move it.

Why this is needed
------------------
A single test is a snapshot. Rides are a continuous stream. Some parameters
move fast (VO2max, MLSS decay within weeks of reduced aerobic stimulus);
others are "sticky" (VLamax / glycolytic capacity reflects fibre type and
moves slowly). Feeding raw rides to the profiler with no memory makes the
estimate collapse whenever an athlete simply didn't ride maximally — which is
most rides. Conversely, never decaying a stale test means the profile lies
when the athlete has actually detrained.

The manager expresses each parameter's *current* prior as (mean, std), where:

  * mean  = the last measured value, optionally decayed toward a floor when
            load has been low since the measurement.
  * std   = grows with the age of the measurement, faster for fast-moving
            parameters and slower for sticky ones, and grows further when
            training load has been low (uncertainty about an unsustained
            value).

A wide std lets fresh ride data dominate; a narrow std keeps the measured
value anchored. This is the standard Bayesian behaviour — the manager only
*chooses the std*, the actual inference stays in bayesian_profiler.

No decay model is reimplemented here: when a detraining model is available it
is used to move the mean; otherwise the mean is held and only the std grows.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, Optional, Union

import numpy as np


# Per-parameter dynamics. half_life_days is the time over which the prior std
# roughly doubles in the absence of load (how fast we stop trusting an old
# measurement). VLamax is sticky (long half-life); VO2max and MLSS move faster.
@dataclass(frozen=True)
class ParameterDynamics:
    base_std: float          # prior std right after a fresh measurement
    half_life_days: float    # std-growth time constant (no/low load)
    floor: float             # physiological floor the mean can decay toward
    sticky: bool = False     # informational flag
    max_std_multiple: float = 8.0  # cap on std growth (prior becomes flat)

_DYNAMICS: Dict[str, ParameterDynamics] = {
    # VO2max (ml/kg/min): moves on a scale of weeks without aerobic stimulus.
    "vo2max":  ParameterDynamics(base_std=2.5, half_life_days=42.0, floor=30.0, max_std_multiple=8.0),
    # MLSS (W): tracks aerobic fitness, similar timescale to VO2max.
    "mlss":    ParameterDynamics(base_std=8.0, half_life_days=42.0, floor=120.0, max_std_multiple=8.0),
    # VLamax (mmol/L/s): glycolytic capacity, fibre-type linked -> sticky.
    "vlamax":  ParameterDynamics(base_std=0.06, half_life_days=180.0, floor=0.20, sticky=True, max_std_multiple=6.0),
}


@dataclass
class MeasuredProfile:
    """A measured physiological profile used as the prior source."""
    measured_on: date
    vo2max: Optional[float] = None          # ml/kg/min
    mlss_watts: Optional[float] = None       # W
    vlamax: Optional[float] = None           # mmol/L/s
    source: str = "lab_test"                 # provenance label
    notes: str = ""

    @staticmethod
    def _to_date(d: Union[date, datetime, str]) -> date:
        if isinstance(d, datetime):
            return d.date()
        if isinstance(d, date):
            return d
        return datetime.fromisoformat(str(d)).date()

    def __post_init__(self):
        self.measured_on = self._to_date(self.measured_on)


@dataclass
class PriorState:
    """The current (time/load-adjusted) prior for one parameter."""
    parameter: str
    mean: float
    std: float
    age_days: int
    load_factor: float
    decayed: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "parameter": self.parameter,
            "mean": round(self.mean, 3),
            "std": round(self.std, 3),
            "age_days": self.age_days,
            "load_factor": round(self.load_factor, 2),
            "decayed": self.decayed,
        }


class PhysiologicalPriorManager:
    """
    Turns a measured profile + elapsed time + training load into the
    (mean, std) priors the Bayesian profiler should use right now.

    load_factor convention (caller supplies it, typically from Layer 1):
        1.0  -> training load fully maintains the measured value
        0.0  -> no load at all since the measurement (max detraining pressure)
    Values in between scale the detraining pressure linearly. If you don't
    have a load signal, pass load_factor=1.0 (hold the mean, only widen std
    with age) or 0.5 for a neutral assumption.
    """

    def __init__(self, profile: MeasuredProfile):
        self.profile = profile

    def _age_days(self, as_of: Union[date, datetime, str]) -> int:
        as_of_d = MeasuredProfile._to_date(as_of)
        return max(0, (as_of_d - self.profile.measured_on).days)

    def _prior_for(
        self,
        parameter: str,
        measured_value: Optional[float],
        as_of: Union[date, datetime, str],
        load_factor: float,
        detraining_fn=None,
    ) -> Optional[PriorState]:
        if measured_value is None:
            return None
        dyn = _DYNAMICS[parameter]
        age = self._age_days(as_of)
        load_factor = float(np.clip(load_factor, 0.0, 1.0))

        # --- std growth -------------------------------------------------
        # Base doubling over half_life_days; low load shortens the effective
        # half-life (we trust an unsustained value less, faster).
        # effective_half_life shrinks toward half_life_days/3 as load -> 0.
        eff_half_life = dyn.half_life_days * (0.33 + 0.67 * load_factor)
        growth = 2.0 ** (age / max(eff_half_life, 1.0))
        # Cap growth: once the std reaches a few multiples of base, the prior
        # is already effectively uninformative — the data fully dominates. An
        # uncapped exponential would otherwise produce absurd (1e8) stds for
        # old, low-load measurements and can destabilise downstream sampling.
        growth = min(growth, dyn.max_std_multiple)
        std = dyn.base_std * growth

        # --- mean decay -------------------------------------------------
        # Only decay the mean when load is below maintenance AND a detraining
        # model is supplied; otherwise hold the measured mean (std carries the
        # uncertainty). Decay pressure scales with (1 - load_factor).
        mean = float(measured_value)
        decayed = False
        if detraining_fn is not None and load_factor < 1.0 and age > 0:
            pressure = 1.0 - load_factor
            try:
                decayed_value = float(
                    detraining_fn(
                        parameter=parameter,
                        value=measured_value,
                        age_days=age,
                        pressure=pressure,
                        floor=dyn.floor,
                    )
                )
                if np.isfinite(decayed_value):
                    mean = float(np.clip(decayed_value, dyn.floor, measured_value))
                    decayed = mean < measured_value - 1e-6
            except Exception:
                # Detraining model failed -> hold mean, std already widened.
                pass

        return PriorState(
            parameter=parameter,
            mean=mean,
            std=float(std),
            age_days=age,
            load_factor=load_factor,
            decayed=decayed,
        )

    def current_priors(
        self,
        as_of: Union[date, datetime, str],
        load_factor: float = 1.0,
        detraining_fn=None,
    ) -> Dict[str, PriorState]:
        """
        Compute the current prior (mean, std) for every measured parameter.

        detraining_fn (optional): callable
            (parameter, value, age_days, pressure, floor) -> decayed_value.
            Use the backend's existing detraining model here. If None, means
            are held and only the std grows with age/load.
        """
        out: Dict[str, PriorState] = {}
        for param, value in (
            ("vo2max", self.profile.vo2max),
            ("mlss", self.profile.mlss_watts),
            ("vlamax", self.profile.vlamax),
        ):
            ps = self._prior_for(param, value, as_of, load_factor, detraining_fn)
            if ps is not None:
                out[param] = ps
        return out

    def bayesian_kwargs(
        self,
        as_of: Union[date, datetime, str],
        load_factor: float = 1.0,
        detraining_fn=None,
    ) -> Dict[str, Any]:
        """
        Produce the prior_* keyword arguments for
        bayesian_profiler.bayesian_metabolic_snapshot, so a measured profile
        becomes the prior and ride data updates the posterior.

        Only VO2max and VLamax are passed (the Bayesian profiler's free
        parameters); MLSS is derived by the forward model from those two, so
        its prior is informational and exposed via current_priors().
        """
        priors = self.current_priors(as_of, load_factor, detraining_fn)
        kwargs: Dict[str, Any] = {}
        if "vo2max" in priors:
            kwargs["prior_vo2_mean"] = priors["vo2max"].mean
            kwargs["prior_vo2_std"] = priors["vo2max"].std
        if "vlamax" in priors:
            kwargs["prior_vla_mean"] = priors["vlamax"].mean
            kwargs["prior_vla_std"] = priors["vlamax"].std
        return kwargs
