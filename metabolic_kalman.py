"""
Metabolic Kalman Filter
========================

State-space model that tracks an athlete's physiological state
(VO2max, VLamax) over time, using:

  - **Predict step** (daily): decay + training stimulus adaptation
  - **Update step** (when a TEST session provides qualified anchors):
    correct the state estimate using the Mader forward model

This closes the loop between:
  - `interval_detector` (classifies sessions, extracts stimulus_vector)
  - `bayesian_profiler` (provides initial state with uncertainty)
  - This module (propagates the state through time)

State vector
------------
x = [VO2max, VLamax]  (2D)

MLSS, FatMax, MAP are derived from the state at query time via the
Mader forward model — they are NOT independent state variables.

Transition model (predict)
--------------------------
x_{t+1} = x_t + decay(x_t) + adaptation(stimulus_t)

Where:
  - decay is a daily fractional loss toward a population baseline,
    modulated by how long since the last stimulus in each system
  - adaptation is a positive daily effect from training stimulus,
    proportional to the stimulus_vector from interval_detector

Decay rates (default, from literature):
  - VO2max: -0.3%/day of inactivity (Mujika 2000: ~5% in 2 weeks)
  - VLamax: -0.15%/day (glycolytic decays slower; Mujika & Padilla 2001)

Observation model (update)
--------------------------
When a TEST produces qualified_anchors, we observe power at known
durations. The observation function h(x) = Mader forward model.
Since h is nonlinear, we use the Unscented transform.

Initialization
--------------
From bayesian_profiler posterior:
  x0 = [posterior_mean_vo2, posterior_mean_vla]
  P0 = diag([posterior_std_vo2², posterior_std_vla²])

Or from deterministic profiler:
  x0 = [estimated_vo2max, estimated_vlamax]
  P0 = diag([10², 0.25²])  # generous initial uncertainty

Tier: MODEL — decay/adaptation rates are evidence-informed but
not individually validated. The Kalman formalism itself is REFERENCE
(well-established signal processing).

Dependencies: numpy only.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from datetime import date, timedelta
import numpy as np


# =============================================================================
# Default parameters (literature-informed, overridable)
# =============================================================================

@dataclass
class DecayConfig:
    """
    Daily fractional decay rates when NO stimulus is received.
    
    Literature sources:
      - Mujika & Padilla 2000: VO2max declines 4-14% in 4 weeks
        of detraining → ~0.15-0.50%/day, midpoint ~0.30%/day
      - Coyle et al. 1984: VO2max -7% in 3 weeks → 0.33%/day
      - VLamax: less studied; glycolytic enzymes (PFK, LDH) decay
        slower than oxidative enzymes → ~50% of VO2max decay rate
    """
    vo2max_daily_decay_pct: float = 0.30   # %/day without VO2max stimulus
    vlamax_daily_decay_pct: float = 0.15   # %/day without glycolytic stimulus
    
    # Below these, decay stops (population floor)
    vo2max_floor: float = 25.0             # ml/kg/min (untrained sedentary)
    vlamax_floor: float = 0.15             # mmol/L/s (very low glycolytic)
    
    # Stimulus thresholds: below this many minutes/day, full decay applies
    # Above, decay is proportionally reduced.
    vo2max_stimulus_threshold_min: float = 5.0   # min of VO2max stimulus to halt decay
    vlamax_stimulus_threshold_min: float = 3.0   # min of neuromuscular/anaerobic stimulus


@dataclass
class AdaptationConfig:
    """
    Daily adaptation rates from training stimulus.
    
    These are MUCH harder to pin down from literature because
    adaptation depends on training history, genetics, and recovery.
    The defaults are conservative (slow adaptation).
    
    Units: %/minute of stimulus. So 10 min of VO2max stimulus
    at the default rate = 10 * 0.02 = 0.2%/day adaptation.
    """
    vo2max_adaptation_per_min: float = 0.020   # %/min of VO2max stimulus
    vlamax_adaptation_per_min: float = 0.015   # %/min of neuromuscular stimulus
    
    # Maximum daily adaptation (cap to prevent unrealistic jumps)
    vo2max_max_daily_adaptation_pct: float = 0.5
    vlamax_max_daily_adaptation_pct: float = 0.3


# =============================================================================
# State representation
# =============================================================================

@dataclass
class MetabolicState:
    """The estimated state at a point in time."""
    date: date
    
    # State estimates (mean of Kalman state)
    vo2max: float
    vlamax: float
    
    # Uncertainty (sqrt of diagonal of P matrix)
    vo2max_std: float
    vlamax_std: float
    
    # Covariance (off-diagonal of P) — negative means anti-correlated
    vo2_vla_covariance: float
    
    # Derived (from state via Mader)
    mlss_watts: Optional[float] = None
    fatmax_watts: Optional[float] = None
    map_watts: Optional[float] = None
    
    # What happened on this day
    stimulus_applied: Optional[Dict[str, float]] = None
    observation_applied: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date.isoformat(),
            "vo2max": round(self.vo2max, 1),
            "vo2max_std": round(self.vo2max_std, 2),
            "vo2max_ci95": [
                round(self.vo2max - 1.96 * self.vo2max_std, 1),
                round(self.vo2max + 1.96 * self.vo2max_std, 1),
            ],
            "vlamax": round(self.vlamax, 4),
            "vlamax_std": round(self.vlamax_std, 4),
            "mlss_watts": self.mlss_watts,
            "fatmax_watts": self.fatmax_watts,
            "map_watts": self.map_watts,
            "observation_applied": self.observation_applied,
            "stimulus_applied": self.stimulus_applied,
        }


@dataclass
class KalmanTrajectory:
    """Full trajectory of an athlete over time."""
    athlete_id: Optional[str]
    states: List[MetabolicState]
    n_predict_steps: int = 0
    n_update_steps: int = 0
    config: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "athlete_id": self.athlete_id,
            "n_days": len(self.states),
            "n_predict_steps": self.n_predict_steps,
            "n_update_steps": self.n_update_steps,
            "first_date": self.states[0].date.isoformat() if self.states else None,
            "last_date": self.states[-1].date.isoformat() if self.states else None,
            "final_state": self.states[-1].to_dict() if self.states else None,
            "states": [s.to_dict() for s in self.states],
            "tier": "MODEL",
        }


# =============================================================================
# Daily input
# =============================================================================

@dataclass
class DailyInput:
    """What happened on one day — feeds into Kalman predict + update."""
    date: date
    
    # Stimulus from training (from interval_detector.stimulus_vector)
    # These are in MINUTES
    vo2max_stimulus_min: float = 0.0       # time above ~105% FTP
    threshold_stimulus_min: float = 0.0    # time at 90-105% FTP
    anaerobic_stimulus_min: float = 0.0    # time at 120-150% FTP
    neuromuscular_stimulus_min: float = 0.0 # time above 150% FTP
    
    # Qualified anchors from TEST sessions (trigger Kalman update)
    # Format: [(duration_s, power_w), ...]
    test_anchors: Optional[List[Tuple[int, float]]] = None
    
    @property
    def has_test(self) -> bool:
        return bool(self.test_anchors and len(self.test_anchors) >= 2)
    
    @property
    def total_vo2max_related_stimulus(self) -> float:
        """Minutes of stimulus that maintains/builds VO2max."""
        return self.vo2max_stimulus_min + self.anaerobic_stimulus_min * 0.5
    
    @property
    def total_vlamax_related_stimulus(self) -> float:
        """Minutes of stimulus that maintains/builds VLamax."""
        return self.neuromuscular_stimulus_min + self.anaerobic_stimulus_min * 0.7


# =============================================================================
# Unscented Kalman Filter (UKF) for 2-state system
# =============================================================================

def _sigma_points(x: np.ndarray, P: np.ndarray, alpha: float = 1e-3, kappa: float = 0.0):
    """Generate 2n+1 sigma points for the unscented transform."""
    n = len(x)
    lam = alpha ** 2 * (n + kappa) - n
    
    sqrt_matrix = np.linalg.cholesky((n + lam) * P)
    
    sigmas = np.zeros((2 * n + 1, n))
    sigmas[0] = x
    for i in range(n):
        sigmas[i + 1] = x + sqrt_matrix[i]
        sigmas[n + i + 1] = x - sqrt_matrix[i]
    
    # Weights
    wm = np.full(2 * n + 1, 1.0 / (2 * (n + lam)))
    wc = np.full(2 * n + 1, 1.0 / (2 * (n + lam)))
    wm[0] = lam / (n + lam)
    wc[0] = lam / (n + lam) + (1 - alpha ** 2 + 2)  # beta=2 for Gaussian
    
    return sigmas, wm, wc


# =============================================================================
# Core Kalman class
# =============================================================================

class MetabolicKalman:
    """
    Unscented Kalman Filter for tracking [VO2max, VLamax] over time.
    
    Usage:
    
        # Initialize from Bayesian posterior
        kalman = MetabolicKalman(
            x0=[snap.vo2max.mean, snap.vlamax.mean],
            P0=np.diag([snap.vo2max.std**2, snap.vlamax.std**2]),
            weight=72.0,
        )
        
        # Process daily inputs
        for day in workout_history:
            kalman.predict(day)
            if day.has_test:
                kalman.update(day.test_anchors, profiler)
        
        # Get trajectory
        trajectory = kalman.get_trajectory()
    """
    
    def __init__(
        self,
        x0: np.ndarray,
        P0: np.ndarray,
        weight: float,
        athlete_id: Optional[str] = None,
        start_date: Optional[date] = None,
        decay_config: Optional[DecayConfig] = None,
        adaptation_config: Optional[AdaptationConfig] = None,
        process_noise_vo2: float = 0.5,
        process_noise_vla: float = 0.01,
        measurement_noise_w: float = 15.0,
    ):
        """
        Parameters
        ----------
        x0 : ndarray (2,)
            Initial state [VO2max, VLamax].
        P0 : ndarray (2, 2)
            Initial covariance.
        weight : float
            Athlete body weight in kg (for Mader forward model).
        process_noise_vo2, process_noise_vla : float
            Diagonal of Q (process noise covariance).
        measurement_noise_w : float
            Measurement noise in watts (diagonal of R).
        """
        self.x = np.array(x0, dtype=float)
        self.P = np.array(P0, dtype=float)
        self.weight = weight
        self.athlete_id = athlete_id
        
        self.decay = decay_config or DecayConfig()
        self.adapt = adaptation_config or AdaptationConfig()
        
        # Process noise
        self.Q = np.diag([process_noise_vo2 ** 2, process_noise_vla ** 2])
        
        # Measurement noise (per anchor observation)
        self.R_per_anchor = measurement_noise_w ** 2
        
        # State history
        self.current_date = start_date or date.today()
        self._history: List[MetabolicState] = []
        self._n_predict = 0
        self._n_update = 0
        
        # Record initial state
        self._record_state(observation=False, stimulus=None)
    
    def predict(self, daily_input: DailyInput) -> MetabolicState:
        """
        Predict step: advance state by one day with decay + stimulus.
        
        Parameters
        ----------
        daily_input : DailyInput
            Training stimulus for this day.
        
        Returns
        -------
        MetabolicState after prediction (before any update).
        """
        self.current_date = daily_input.date
        
        vo2, vla = self.x
        
        # --- Decay ---
        # VO2max decay: reduced/eliminated by VO2max-related stimulus
        vo2_stim = daily_input.total_vo2max_related_stimulus
        vo2_decay_factor = max(0.0, 1.0 - vo2_stim / self.decay.vo2max_stimulus_threshold_min)
        vo2_decay = -vo2 * (self.decay.vo2max_daily_decay_pct / 100.0) * vo2_decay_factor
        
        # VLamax decay: reduced by neuromuscular/anaerobic stimulus
        vla_stim = daily_input.total_vlamax_related_stimulus
        vla_decay_factor = max(0.0, 1.0 - vla_stim / self.decay.vlamax_stimulus_threshold_min)
        vla_decay = -vla * (self.decay.vlamax_daily_decay_pct / 100.0) * vla_decay_factor
        
        # --- Adaptation ---
        vo2_adapt = min(
            vo2_stim * (self.adapt.vo2max_adaptation_per_min / 100.0) * vo2,
            vo2 * self.adapt.vo2max_max_daily_adaptation_pct / 100.0,
        )
        vla_adapt = min(
            vla_stim * (self.adapt.vlamax_adaptation_per_min / 100.0) * vla,
            vla * self.adapt.vlamax_max_daily_adaptation_pct / 100.0,
        )
        
        # --- Apply ---
        new_vo2 = max(self.decay.vo2max_floor, vo2 + vo2_decay + vo2_adapt)
        new_vla = max(self.decay.vlamax_floor, vla + vla_decay + vla_adapt)
        
        self.x = np.array([new_vo2, new_vla])
        
        # Propagate covariance: P_{t+1} = F * P * F^T + Q
        # F ≈ I (linearized transition is near-identity for small daily changes)
        # So P_{t+1} ≈ P + Q
        self.P = self.P + self.Q
        
        self._n_predict += 1
        
        stim_dict = {
            "vo2max_min": round(vo2_stim, 1),
            "vlamax_min": round(vla_stim, 1),
            "vo2_decay": round(vo2_decay, 3),
            "vla_decay": round(vla_decay, 4),
            "vo2_adapt": round(vo2_adapt, 3),
            "vla_adapt": round(vla_adapt, 4),
        }
        
        state = self._record_state(observation=False, stimulus=stim_dict)
        
        # If the daily input has test anchors, also do an update
        if daily_input.has_test:
            state = self.update(daily_input.test_anchors)
        
        return state
    
    def update(
        self,
        test_anchors: List[Tuple[int, float]],
        profiler=None,
    ) -> MetabolicState:
        """
        Update step: correct state using observed test anchors.
        
        Uses the Unscented transform because the Mader forward model
        h(x) → predicted_power is nonlinear in (VO2max, VLamax).
        
        Parameters
        ----------
        test_anchors : list of (duration_s, power_w)
            Observed max-mean powers from a qualified TEST session.
        profiler : MetabolicProfiler, optional
            If provided, uses the full Mader forward model for h(x).
            If not, uses a simplified power-duration approximation.
        """
        if not test_anchors or len(test_anchors) < 1:
            return self._history[-1] if self._history else None
        
        # Observations
        z = np.array([pw for _, pw in test_anchors])
        durs = [d for d, _ in test_anchors]
        n_obs = len(z)
        
        # Observation function h(x) = predicted power at each duration
        def h(state):
            vo2, vla = state
            if profiler is not None:
                # Full Mader forward model
                eta = profiler.context.expected_eta()
                pcr = profiler._pcr_prior_watts()
                w_grid = np.arange(
                    profiler.const.w_min,
                    max(2000, self.weight * 30) + profiler.const.w_step,
                    profiler.const.w_step,
                )
                la_cap = float(np.clip(10.0 + (vla - 0.2) * 15.0, 8.0, 30.0))
                try:
                    tau, map_est, vo2_act, net = profiler._compute_grid_state(
                        vo2, vla, eta, w_grid
                    )
                    preds = np.array([
                        profiler._pred_power(t, la_cap, tau, map_est, w_grid, vo2_act, net)
                        for t in durs
                    ]) + (pcr * np.exp(-np.maximum(0.0, np.array(durs, float) - 20.0) / 35.0))
                    return preds
                except Exception:
                    pass
            
            # Simplified approximation (fallback)
            # P(t) ≈ MAP * exp(-t/tau) where MAP ∝ VO2max, tau ∝ 1/VLamax
            map_approx = vo2 * self.weight * 0.075
            tau_approx = max(30.0, 600.0 / max(vla, 0.1))
            return np.array([
                map_approx * np.exp(-d / tau_approx) for d in durs
            ])
        
        # --- Unscented transform ---
        try:
            sigmas, wm, wc = _sigma_points(self.x, self.P)
        except np.linalg.LinAlgError:
            # P not positive definite — reset to diagonal
            self.P = np.diag(np.diag(self.P)) + np.eye(2) * 0.01
            sigmas, wm, wc = _sigma_points(self.x, self.P)
        
        n_sigma = len(sigmas)
        
        # Propagate sigma points through h
        Z = np.zeros((n_sigma, n_obs))
        for i, sp in enumerate(sigmas):
            # Bound sigma points to valid range
            sp_bounded = np.clip(sp, [20.0, 0.05], [100.0, 2.0])
            Z[i] = h(sp_bounded)
        
        # Predicted observation mean and covariance
        z_mean = np.sum(wm[:, None] * Z, axis=0)
        
        Pzz = np.zeros((n_obs, n_obs))
        Pxz = np.zeros((2, n_obs))
        for i in range(n_sigma):
            dz = Z[i] - z_mean
            dx = sigmas[i] - self.x
            Pzz += wc[i] * np.outer(dz, dz)
            Pxz += wc[i] * np.outer(dx, dz)
        
        # Measurement noise
        R = np.eye(n_obs) * self.R_per_anchor
        Pzz += R
        
        # Kalman gain
        try:
            K = Pxz @ np.linalg.inv(Pzz)
        except np.linalg.LinAlgError:
            K = Pxz @ np.linalg.pinv(Pzz)
        
        # Innovation
        innovation = z - z_mean
        
        # Update state
        self.x = self.x + K @ innovation
        self.P = self.P - K @ Pzz @ K.T
        
        # Enforce bounds
        self.x = np.clip(self.x, [20.0, 0.05], [100.0, 2.0])
        
        # Ensure P stays positive definite
        self.P = (self.P + self.P.T) / 2
        eigvals = np.linalg.eigvalsh(self.P)
        if np.any(eigvals < 0):
            self.P += np.eye(2) * (abs(eigvals.min()) + 1e-4)
        
        self._n_update += 1
        
        # Update the last state in history
        if self._history:
            self._history[-1] = self._make_state(observation=True,
                                                   stimulus=self._history[-1].stimulus_applied)
        else:
            self._record_state(observation=True, stimulus=None)
        
        return self._history[-1]
    
    def update_from_lab(self, lab_result) -> "MetabolicState":
        """
        Update state using laboratory test results (gold standard).
        
        Lab observations have much lower noise than field-based MMP
        estimates, so the Kalman gain is high — a single lab test
        can dramatically reduce uncertainty.
        
        Parameters
        ----------
        lab_result : LabTestResult
            Normalized lab data (from engines.lab_data).
        
        Returns
        -------
        MetabolicState after the lab-anchored update.
        """
        # Build observation vector and noise from available lab data
        z_list = []      # observations
        H_rows = []      # observation matrix rows (which state element is observed)
        R_diag = []      # measurement noise (diagonal)
        
        if lab_result.has_vo2max:
            z_list.append(lab_result.vo2max_ml_kg_min)
            H_rows.append([1.0, 0.0])   # observes VO2max directly
            R_diag.append(lab_result.vo2max_noise_ml_kg ** 2)
        
        if lab_result.has_vlamax:
            z_list.append(lab_result.vlamax_mmol_L_s)
            H_rows.append([0.0, 1.0])   # observes VLamax directly
            R_diag.append(lab_result.vlamax_noise_mmol ** 2)
        
        if not z_list:
            # No direct state observations — can't do a standard update
            # but we can still record the lab data as metadata
            return self._history[-1] if self._history else self.current_state
        
        z = np.array(z_list)
        H = np.array(H_rows)
        R = np.diag(R_diag)
        
        # Standard Kalman update (linear observation model — H is exact)
        # Innovation
        y = z - H @ self.x
        
        # Innovation covariance
        S = H @ self.P @ H.T + R
        
        # Kalman gain
        try:
            K = self.P @ H.T @ np.linalg.inv(S)
        except np.linalg.LinAlgError:
            K = self.P @ H.T @ np.linalg.pinv(S)
        
        # State update
        self.x = self.x + K @ y
        
        # Covariance update (Joseph form for numerical stability)
        I = np.eye(2)
        IKH = I - K @ H
        self.P = IKH @ self.P @ IKH.T + K @ R @ K.T
        
        # Enforce bounds
        self.x = np.clip(self.x, [20.0, 0.05], [100.0, 2.0])
        
        # Ensure P positive definite
        self.P = (self.P + self.P.T) / 2
        eigvals = np.linalg.eigvalsh(self.P)
        if np.any(eigvals < 0):
            self.P += np.eye(2) * (abs(eigvals.min()) + 1e-4)
        
        self._n_update += 1
        
        # Record state
        stim = {"lab_update": True, "source": str(getattr(lab_result, 'source_label', 'lab'))}
        if self._history:
            self._history[-1] = self._make_state(observation=True, stimulus=stim)
        else:
            self._record_state(observation=True, stimulus=stim)
        
        return self._history[-1]
    
    def _make_state(self, observation: bool, stimulus) -> MetabolicState:
        """Build a MetabolicState from current Kalman state."""
        vo2, vla = self.x
        vo2_std = float(np.sqrt(max(self.P[0, 0], 1e-6)))
        vla_std = float(np.sqrt(max(self.P[1, 1], 1e-6)))
        cov = float(self.P[0, 1])
        
        return MetabolicState(
            date=self.current_date,
            vo2max=float(vo2),
            vlamax=float(vla),
            vo2max_std=vo2_std,
            vlamax_std=vla_std,
            vo2_vla_covariance=cov,
            stimulus_applied=stimulus,
            observation_applied=observation,
        )
    
    def _record_state(self, observation: bool, stimulus) -> MetabolicState:
        """Record the current state into history."""
        state = self._make_state(observation, stimulus)
        self._history.append(state)
        return state
    
    def get_trajectory(self) -> KalmanTrajectory:
        """Return the full trajectory."""
        return KalmanTrajectory(
            athlete_id=self.athlete_id,
            states=list(self._history),
            n_predict_steps=self._n_predict,
            n_update_steps=self._n_update,
            config={
                "decay": {
                    "vo2max_daily_pct": self.decay.vo2max_daily_decay_pct,
                    "vlamax_daily_pct": self.decay.vlamax_daily_decay_pct,
                },
                "adaptation": {
                    "vo2max_per_min": self.adapt.vo2max_adaptation_per_min,
                    "vlamax_per_min": self.adapt.vlamax_adaptation_per_min,
                },
                "process_noise": {
                    "vo2": float(np.sqrt(self.Q[0, 0])),
                    "vla": float(np.sqrt(self.Q[1, 1])),
                },
                "measurement_noise_w": float(np.sqrt(self.R_per_anchor)),
            },
        )
    
    @property
    def current_state(self) -> MetabolicState:
        """Latest estimated state."""
        return self._make_state(False, None)


def process_workout_history(
    daily_inputs: List[DailyInput],
    initial_vo2: float,
    initial_vla: float,
    weight: float,
    initial_vo2_std: float = 5.0,
    initial_vla_std: float = 0.15,
    athlete_id: Optional[str] = None,
    profiler=None,
    decay_config: Optional[DecayConfig] = None,
    adaptation_config: Optional[AdaptationConfig] = None,
) -> KalmanTrajectory:
    """
    Convenience function: process a sequence of daily inputs and
    return the full trajectory.
    
    Parameters
    ----------
    daily_inputs : list of DailyInput
        Chronologically ordered daily training data.
    initial_vo2, initial_vla : float
        Starting state (from bayesian_profiler or deterministic profiler).
    initial_vo2_std, initial_vla_std : float
        Initial uncertainty (from bayesian_profiler posterior or default).
    weight : float
        Athlete body weight in kg.
    profiler : MetabolicProfiler, optional
        If provided, uses full Mader model for observation updates.
    
    Returns
    -------
    KalmanTrajectory with daily state estimates.
    """
    x0 = np.array([initial_vo2, initial_vla])
    P0 = np.diag([initial_vo2_std ** 2, initial_vla_std ** 2])
    
    start = daily_inputs[0].date if daily_inputs else date.today()
    
    kalman = MetabolicKalman(
        x0, P0, weight,
        athlete_id=athlete_id,
        start_date=start,
        decay_config=decay_config,
        adaptation_config=adaptation_config,
    )
    
    for di in daily_inputs:
        if di.has_test and profiler:
            # Set profiler for the update step
            kalman.predict(di)
            # update is called automatically inside predict when has_test
        else:
            kalman.predict(di)
    
    return kalman.get_trajectory()
