"""Test calibration engine."""
import numpy as np

from snowden.calibrate import Calibrator


class TestBrierScore:
    def test_perfect_predictions(self):
        preds = np.array([1.0, 0.0, 1.0, 0.0])
        outcomes = np.array([1, 0, 1, 0])
        assert Calibrator.brier_score(preds, outcomes) == 0.0

    def test_worst_predictions(self):
        preds = np.array([0.0, 1.0])
        outcomes = np.array([1, 0])
        assert Calibrator.brier_score(preds, outcomes) == 1.0

    def test_moderate_predictions(self):
        preds = np.array([0.7, 0.3, 0.8, 0.2])
        outcomes = np.array([1, 0, 1, 0])
        score = Calibrator.brier_score(preds, outcomes)
        assert 0.0 < score < 0.15

    def test_uniform_predictions(self):
        preds = np.array([0.5, 0.5, 0.5, 0.5])
        outcomes = np.array([1, 0, 1, 0])
        assert Calibrator.brier_score(preds, outcomes) == 0.25


class TestCalibrator:
    def test_correct_without_fitting(self):
        cal = Calibrator()
        assert cal.correct(0.7) == 0.7

    def test_correct_preserves_range(self):
        cal = Calibrator()
        for p in [0.01, 0.1, 0.5, 0.9, 0.99]:
            result = cal.correct(p)
            assert 0.0 <= result <= 1.0
