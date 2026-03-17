"""
snowden/calibrate.py

Tracks prediction accuracy. Fits Platt scaling to correct systematic LLM bias.
Computes Brier score and reliability diagrams.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import numpy as np
from sklearn.linear_model import LogisticRegression

from snowden.config import settings
from snowden.types import CalibrationReport

if TYPE_CHECKING:
    from snowden.store import Store


class Calibrator:
    def __init__(self) -> None:
        self._scaler = LogisticRegression(C=1.0, solver="lbfgs")
        self._fitted = False

    @property
    def is_fitted(self) -> bool:
        return self._fitted

    async def fit_from_db(self, store: Store, min_samples: int | None = None) -> bool:
        """Load resolved predictions and fit Platt scaling. Returns True if fitted."""
        if min_samples is None:
            min_samples = settings.calibration_min_samples
        resolved = await store.get_resolved_predictions()
        if len(resolved) < min_samples:
            return False

        preds = resolved["p_est_raw"].to_numpy().astype(np.float64)
        actuals = resolved["outcome"].to_numpy().astype(np.int32)

        # Clip to avoid log(0)
        preds = np.clip(preds, settings.calibration_clip_low, settings.calibration_clip_high)
        logits = np.log(preds / (1.0 - preds)).reshape(-1, 1)

        self._scaler.fit(logits, actuals)
        self._fitted = True
        return True

    def correct(self, raw_prob: float) -> float:
        """Apply Platt scaling to raw LLM probability."""
        if not self._fitted:
            return raw_prob
        raw_prob = float(
            np.clip(raw_prob, settings.calibration_clip_low, settings.calibration_clip_high)
        )
        logit = np.log(raw_prob / (1.0 - raw_prob))
        return float(self._scaler.predict_proba([[logit]])[0][1])

    @staticmethod
    def brier_score(predictions: np.ndarray, outcomes: np.ndarray) -> float:
        """Mean squared error between predicted probabilities and actual outcomes."""
        return float(np.mean((predictions - outcomes) ** 2))

    async def generate_report(self, store: Store) -> CalibrationReport | None:
        """Generate a full calibration report from resolved predictions."""
        resolved = await store.get_resolved_predictions()
        if len(resolved) < settings.calibration_min_report:
            return None

        preds = resolved["p_est"].to_numpy().astype(np.float64)
        actuals = resolved["outcome"].to_numpy().astype(np.int32)

        brier = self.brier_score(preds, actuals)

        # Reliability diagram: bucket predictions into deciles
        buckets: dict[str, dict[str, float]] = {}
        for low in np.arange(0, 1.0, 0.1):
            high = low + 0.1
            mask = (preds >= low) & (preds < high)
            count = int(mask.sum())
            if count > 0:
                bucket_name = f"{low:.1f}-{high:.1f}"
                buckets[bucket_name] = {
                    "predicted": float(preds[mask].mean()),
                    "actual": float(actuals[mask].mean()),
                    "count": float(count),
                }

        # Bias detection
        over_mask = preds > 0.5
        under_mask = preds <= 0.5
        overconf = (
            float((preds[over_mask] - actuals[over_mask]).mean())
            if over_mask.sum() > 0
            else 0.0
        )
        underconf = (
            float((actuals[under_mask] - preds[under_mask]).mean())
            if under_mask.sum() > 0
            else 0.0
        )

        return CalibrationReport(
            brier_score=brier,
            n_predictions=len(preds),
            n_resolved=int(actuals.sum()) + int((1 - actuals).sum()),
            overconfidence_bias=overconf,
            underconfidence_bias=underconf,
            reliability_buckets=buckets,
            platt_fitted=self._fitted,
            timestamp=datetime.now(UTC),
        )
