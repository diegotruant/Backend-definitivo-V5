"""
Physics-informed residual MLP for Mader corrections
====================================================

Historical note: this module was exported as ``neural_ode``. That name implied a
Chen-2018 Neural ODE; the implementation is a residual MLP that learns small
corrections on top of the Mader forward model.

Two components, each replacing a fixed-equation counterpart with a
LEARNABLE model:

1. **NeuralPowerDuration** — replaces the Mader power-duration curve
   with a neural network that learns athlete-specific corrections.
   Starts from Mader (correction = 0), fine-tunes on test data.

2. **NeuralDynamics** — replaces the linear decay+adaptation in the
   Kalman filter with a learned temporal model. Trains on longitudinal
   data (multiple snapshots over time).

Both use pure numpy for inference and scipy.optimize for training.
No PyTorch/JAX/TensorFlow required.

Architecture
------------
Each model is a 2-layer MLP with tanh activations:

  input → Linear(n_in, n_hidden) → tanh → Linear(n_hidden, n_out) → output

For NeuralPowerDuration:
  - Input: [log(duration), mader_prediction, vo2max, vlamax]  (4D)
  - Output: [power_correction]  (1D)
  - Hidden: 16 neurons → 4×16 + 16 + 16×1 + 1 = 97 trainable params
  - Total predicted power = mader_prediction + power_correction

For NeuralDynamics:
  - Input: [vo2max, vlamax, vo2_stimulus, vla_stimulus]  (4D)
  - Output: [delta_vo2, delta_vla]  (2D)
  - Hidden: 16 neurons → 4×16 + 16 + 16×2 + 2 = 114 trainable params
  - Next state = current_state + neural_delta

Physics-informed initialization
-------------------------------
All weights initialized to ZERO (or near-zero) so the neural correction
starts at zero. This means:
  - Before any training, the model is EXACTLY Mader (power-duration)
    or EXACTLY the linear decay model (dynamics).
  - Training only adjusts WHERE Mader is wrong.
  - With limited data, the correction stays small (regularization ensures
    this) — the model is conservative, not overfit.

This is the "residual learning" principle from He et al. 2015, applied
to physiology instead of image recognition.

Tier: MODEL (the architecture is a modeling choice; the learned parameters
are data-dependent).

Training
--------
Uses scipy.optimize.minimize with L-BFGS-B:
  - Loss = MSE(predicted, observed) + lambda * L2(weights)
  - L-BFGS-B handles bounds efficiently
  - For 97-114 parameters, converges in <1 second on typical data

When to use
-----------
- **NeuralPowerDuration**: when Mader under/over-predicts for a specific
  athlete despite correct VO2max/VLamax estimates. The correction learns
  the athlete-specific deviation.
- **NeuralDynamics**: when the linear decay model doesn't capture the
  athlete's actual training response. Requires ≥3 longitudinal snapshots
  (e.g. monthly tests over ≥3 months).
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
from scipy.optimize import minimize


# =============================================================================
# MLP implementation (pure numpy)
# =============================================================================

class TinyMLP:
    """
    2-layer MLP: input → tanh(W1 x + b1) → W2 h + b2 → output
    
    Weights stored as a flat vector for compatibility with scipy.optimize.
    """
    
    def __init__(self, n_in: int, n_hidden: int, n_out: int, seed: int = 0):
        self.n_in = n_in
        self.n_hidden = n_hidden
        self.n_out = n_out
        
        # Parameter counts
        self.n_w1 = n_in * n_hidden
        self.n_b1 = n_hidden
        self.n_w2 = n_hidden * n_out
        self.n_b2 = n_out
        self.n_params = self.n_w1 + self.n_b1 + self.n_w2 + self.n_b2
        
        # Initialize near-zero (residual learning: correction starts at 0)
        rng = np.random.default_rng(seed)
        self.params = rng.normal(0, 0.01, self.n_params)
    
    def _unpack(self, params: Optional[np.ndarray] = None):
        """Unpack flat param vector into weight matrices."""
        p = params if params is not None else self.params
        i = 0
        W1 = p[i:i + self.n_w1].reshape(self.n_hidden, self.n_in)
        i += self.n_w1
        b1 = p[i:i + self.n_b1]
        i += self.n_b1
        W2 = p[i:i + self.n_w2].reshape(self.n_out, self.n_hidden)
        i += self.n_w2
        b2 = p[i:i + self.n_b2]
        return W1, b1, W2, b2
    
    def forward(self, x: np.ndarray, params: Optional[np.ndarray] = None) -> np.ndarray:
        """
        Forward pass.
        
        Parameters
        ----------
        x : ndarray (n_in,) or (batch, n_in)
        params : ndarray, optional. If None, uses self.params.
        
        Returns
        -------
        ndarray (n_out,) or (batch, n_out)
        """
        W1, b1, W2, b2 = self._unpack(params)
        
        single = x.ndim == 1
        if single:
            x = x.reshape(1, -1)
        
        # Layer 1: tanh activation
        h = np.tanh(x @ W1.T + b1)
        # Layer 2: linear output
        out = h @ W2.T + b2
        
        return out.squeeze() if single else out
    
    def set_params(self, params: np.ndarray):
        self.params = params.copy()
    
    def get_params(self) -> np.ndarray:
        return self.params.copy()


# =============================================================================
# NeuralPowerDuration — learnable correction to Mader
# =============================================================================

@dataclass
class NeuralPDTrainingResult:
    """Output of NeuralPowerDuration.fit()."""
    success: bool
    n_iterations: int
    final_loss: float
    mse_before: float         # MSE with zero correction (pure Mader)
    mse_after: float          # MSE after training
    improvement_pct: float    # how much better
    n_train_points: int
    regularization_lambda: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "n_iterations": self.n_iterations,
            "final_loss": round(self.final_loss, 4),
            "mse_before": round(self.mse_before, 2),
            "mse_after": round(self.mse_after, 2),
            "improvement_pct": round(self.improvement_pct, 1),
            "n_train_points": self.n_train_points,
        }


class NeuralPowerDuration:
    """
    Mader + neural correction for the power-duration curve.
    
    predicted_power(duration) = mader_power(duration) + correction(duration)
    
    Where correction is a small MLP that starts at zero (untrained) and
    learns athlete-specific deviations when fit() is called.
    """
    
    def __init__(self, n_hidden: int = 16, seed: int = 42):
        # Input: [log(duration), mader_pred_normalized, vo2max_norm, vlamax_norm]
        self.net = TinyMLP(n_in=4, n_hidden=n_hidden, n_out=1, seed=seed)
        self._trained = False
        self._normalization: Dict[str, float] = {}
    
    def predict(
        self,
        durations: np.ndarray,
        mader_predictions: np.ndarray,
        vo2max: float,
        vlamax: float,
    ) -> np.ndarray:
        """
        Predict power at given durations.
        
        If untrained: returns mader_predictions unchanged.
        If trained: returns mader_predictions + learned correction.
        """
        if not self._trained:
            return mader_predictions.copy()
        
        # Build input features
        n = len(durations)
        X = np.column_stack([
            np.log(np.maximum(durations, 1.0)) / np.log(3600),  # normalize log(dur)
            mader_predictions / max(self._normalization.get("power_scale", 300), 1),
            np.full(n, vo2max / 60.0),   # normalize
            np.full(n, vlamax / 0.5),    # normalize
        ])
        
        corrections = self.net.forward(X)
        if corrections.ndim > 1:
            corrections = corrections[:, 0]
        
        # Scale correction back to watts
        power_scale = self._normalization.get("power_scale", 300)
        return mader_predictions + corrections * power_scale * 0.1  # cap correction at ~10%
    
    def fit(
        self,
        durations: np.ndarray,
        observed_powers: np.ndarray,
        mader_predictions: np.ndarray,
        vo2max: float,
        vlamax: float,
        reg_lambda: float = 0.01,
        max_iter: int = 500,
    ) -> NeuralPDTrainingResult:
        """
        Train the neural correction on athlete test data.
        
        Parameters
        ----------
        durations : ndarray
            Test durations in seconds.
        observed_powers : ndarray
            Observed max-mean powers (from TEST sessions).
        mader_predictions : ndarray
            Mader model predictions at same durations.
        vo2max, vlamax : float
            Current athlete state.
        reg_lambda : float
            L2 regularization weight. Higher → smaller corrections.
        max_iter : int
            Max L-BFGS-B iterations.
        
        Returns
        -------
        NeuralPDTrainingResult
        """
        n = len(durations)
        if n < 3:
            return NeuralPDTrainingResult(
                success=False, n_iterations=0, final_loss=0,
                mse_before=0, mse_after=0, improvement_pct=0,
                n_train_points=n, regularization_lambda=reg_lambda,
            )
        
        # Normalization
        power_scale = max(float(np.mean(observed_powers)), 1.0)
        self._normalization = {"power_scale": power_scale}
        
        # Input features
        X = np.column_stack([
            np.log(np.maximum(durations, 1.0)) / np.log(3600),
            mader_predictions / power_scale,
            np.full(n, vo2max / 60.0),
            np.full(n, vlamax / 0.5),
        ])
        
        # Target: residuals (what Mader gets wrong)
        target_corrections = (observed_powers - mader_predictions) / (power_scale * 0.1)
        
        # MSE before training (pure Mader)
        mse_before = float(np.mean((observed_powers - mader_predictions) ** 2))
        
        def loss_fn(params):
            corrections = self.net.forward(X, params)
            if corrections.ndim > 1:
                corrections = corrections[:, 0]
            mse = float(np.mean((corrections - target_corrections) ** 2))
            reg = reg_lambda * float(np.sum(params ** 2))
            return mse + reg
        
        # Optimize
        result = minimize(
            loss_fn,
            self.net.get_params(),
            method="L-BFGS-B",
            options={"maxiter": max_iter, "ftol": 1e-10},
        )
        
        self.net.set_params(result.x)
        self._trained = True
        
        # MSE after training
        final_preds = self.predict(durations, mader_predictions, vo2max, vlamax)
        mse_after = float(np.mean((observed_powers - final_preds) ** 2))
        
        improvement = max(0, (1 - mse_after / max(mse_before, 1e-6)) * 100)
        
        return NeuralPDTrainingResult(
            success=result.success,
            n_iterations=result.nit,
            final_loss=float(result.fun),
            mse_before=mse_before,
            mse_after=mse_after,
            improvement_pct=improvement,
            n_train_points=n,
            regularization_lambda=reg_lambda,
        )
    
    def get_state(self) -> Dict[str, Any]:
        """Serialize for storage/transfer."""
        return {
            "trained": self._trained,
            "params": self.net.get_params().tolist(),
            "normalization": self._normalization,
            "n_params": self.net.n_params,
            "architecture": f"MLP({self.net.n_in}, {self.net.n_hidden}, {self.net.n_out})",
        }
    
    def load_state(self, state: Dict[str, Any]):
        """Restore from serialized state."""
        self.net.set_params(np.array(state["params"]))
        self._trained = state.get("trained", True)
        self._normalization = state.get("normalization", {})


# =============================================================================
# NeuralDynamics — learnable temporal evolution for the Kalman filter
# =============================================================================

@dataclass
class DynamicsTrainingResult:
    """Output of NeuralDynamics.fit()."""
    success: bool
    n_iterations: int
    final_loss: float
    n_transitions: int
    mse_vo2: float
    mse_vla: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "n_iterations": self.n_iterations,
            "final_loss": round(self.final_loss, 6),
            "n_transitions": self.n_transitions,
            "mse_vo2": round(self.mse_vo2, 4),
            "mse_vla": round(self.mse_vla, 6),
        }


class NeuralDynamics:
    """
    Learnable state transition for [VO2max, VLamax].
    
    next_state = current_state + neural_delta(current_state, stimulus)
    
    Replaces the linear decay+adaptation in MetabolicKalman when
    enough longitudinal data is available.
    
    Requires ≥3 state transitions (≥4 snapshots over time) to train.
    With fewer, falls back to the linear model.
    """
    
    def __init__(self, n_hidden: int = 16, seed: int = 42):
        # Input: [vo2max_norm, vlamax_norm, vo2_stimulus_norm, vla_stimulus_norm]
        # Output: [delta_vo2_norm, delta_vla_norm]
        self.net = TinyMLP(n_in=4, n_hidden=n_hidden, n_out=2, seed=seed)
        self._trained = False
        self._normalization: Dict[str, float] = {
            "vo2_scale": 60.0,
            "vla_scale": 0.5,
            "stim_scale": 30.0,
            "delta_scale": 1.0,
        }
    
    def predict_delta(
        self,
        vo2max: float,
        vlamax: float,
        vo2_stimulus_min: float,
        vla_stimulus_min: float,
        days: float = 1.0,
    ) -> Tuple[float, float]:
        """
        Predict the daily change in [VO2max, VLamax].
        
        If untrained: returns (0, 0) — no correction to the base model.
        If trained: returns the learned delta.
        """
        if not self._trained:
            return (0.0, 0.0)
        
        s = self._normalization
        x = np.array([
            vo2max / s["vo2_scale"],
            vlamax / s["vla_scale"],
            vo2_stimulus_min / s["stim_scale"],
            vla_stimulus_min / s["stim_scale"],
        ])
        
        delta_norm = self.net.forward(x)
        delta_vo2 = float(delta_norm[0]) * s["delta_scale"] * days
        delta_vla = float(delta_norm[1]) * s["delta_scale"] * 0.01 * days
        
        return (delta_vo2, delta_vla)
    
    def fit(
        self,
        transitions: List[Dict[str, Any]],
        reg_lambda: float = 0.1,
        max_iter: int = 500,
    ) -> DynamicsTrainingResult:
        """
        Train on observed state transitions.
        
        Parameters
        ----------
        transitions : list of dict
            Each dict: {
                "vo2_before": float, "vla_before": float,
                "vo2_after": float, "vla_after": float,
                "vo2_stimulus_min": float, "vla_stimulus_min": float,
                "days_between": float,
            }
        reg_lambda : float
            L2 regularization.
        
        Returns
        -------
        DynamicsTrainingResult
        """
        n = len(transitions)
        if n < 3:
            return DynamicsTrainingResult(
                success=False, n_iterations=0, final_loss=0,
                n_transitions=n, mse_vo2=0, mse_vla=0,
            )
        
        s = self._normalization
        
        # Build training data
        X = np.zeros((n, 4))
        Y = np.zeros((n, 2))
        for i, t in enumerate(transitions):
            X[i] = [
                t["vo2_before"] / s["vo2_scale"],
                t["vla_before"] / s["vla_scale"],
                t["vo2_stimulus_min"] / s["stim_scale"],
                t["vla_stimulus_min"] / s["stim_scale"],
            ]
            days = max(t.get("days_between", 1), 1)
            Y[i] = [
                (t["vo2_after"] - t["vo2_before"]) / (s["delta_scale"] * days),
                (t["vla_after"] - t["vla_before"]) / (s["delta_scale"] * 0.01 * days),
            ]
        
        def loss_fn(params):
            preds = self.net.forward(X, params)
            mse = float(np.mean((preds - Y) ** 2))
            reg = reg_lambda * float(np.sum(params ** 2))
            return mse + reg
        
        result = minimize(
            loss_fn,
            self.net.get_params(),
            method="L-BFGS-B",
            options={"maxiter": max_iter, "ftol": 1e-12},
        )
        
        self.net.set_params(result.x)
        self._trained = True
        
        # Compute per-param MSE
        final_preds = self.net.forward(X)
        mse_vo2 = float(np.mean((final_preds[:, 0] - Y[:, 0]) ** 2)) * s["delta_scale"] ** 2
        mse_vla = float(np.mean((final_preds[:, 1] - Y[:, 1]) ** 2)) * (s["delta_scale"] * 0.01) ** 2
        
        return DynamicsTrainingResult(
            success=result.success,
            n_iterations=result.nit,
            final_loss=float(result.fun),
            n_transitions=n,
            mse_vo2=mse_vo2,
            mse_vla=mse_vla,
        )
    
    def get_state(self) -> Dict[str, Any]:
        return {
            "trained": self._trained,
            "params": self.net.get_params().tolist(),
            "normalization": self._normalization,
            "n_params": self.net.n_params,
        }
    
    def load_state(self, state: Dict[str, Any]):
        self.net.set_params(np.array(state["params"]))
        self._trained = state.get("trained", True)
        self._normalization = state.get("normalization", self._normalization)
