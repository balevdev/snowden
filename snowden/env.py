"""
snowden/env.py

Gymnasium replay environment for parameter sweeps.
Replays historical paper-trade data to test strategy parameters.
NOT for RL training. For backtesting Kelly divisors, edge thresholds, etc.
"""
from __future__ import annotations

from typing import Any

import gymnasium as gym
import numpy as np
import polars as pl  # noqa: TCH002
from gymnasium import spaces

_DEFAULT_SPREAD = 0.02
_DEFAULT_DAYS = 14.0


class SnowdenReplayEnv(gym.Env):  # type: ignore[type-arg]
    metadata = {"render_modes": ["human"]}

    def __init__(
        self,
        predictions: pl.DataFrame,
        initial_bankroll: float = 2000.0,
    ) -> None:
        super().__init__()
        self._preds = predictions.sort("ts")
        self._idx = 0
        self._bankroll = initial_bankroll
        self._initial = initial_bankroll
        self._peak = initial_bankroll

        # Obs: [p_est, p_market, edge, confidence, spread, days_to_resolve]
        self.observation_space = spaces.Box(-1, 365, shape=(6,), dtype=np.float32)
        # Action: [skip, small(5%), medium(10%), large(20%)]
        self.action_space = spaces.Discrete(4)

    def reset(
        self,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        super().reset(seed=seed)
        self._idx = 0
        self._bankroll = self._initial
        self._peak = self._initial
        return self._obs(), {}

    def step(
        self, action: int
    ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        row = self._preds.row(self._idx, named=True)
        size_map = {0: 0.0, 1: 0.05, 2: 0.10, 3: 0.20}
        frac = size_map[action]
        bet = frac * self._bankroll

        pnl = 0.0
        if row.get("resolved") and row.get("outcome") is not None:
            if row["p_est"] > row["p_market"]:
                pnl = bet * (row["outcome"] / row["p_market"] - 1)
            else:
                pnl = bet * ((1 - row["outcome"]) / (1 - row["p_market"]) - 1)

        self._bankroll += pnl
        self._peak = max(self._peak, self._bankroll)
        self._idx += 1
        done = self._idx >= len(self._preds)
        drawdown = (
            (self._peak - self._bankroll) / self._peak if self._peak > 0 else 0
        )

        return (
            self._obs(),
            pnl,
            done,
            False,
            {
                "bankroll": self._bankroll,
                "drawdown": drawdown,
                "peak": self._peak,
            },
        )

    def _obs(self) -> np.ndarray:
        if self._idx >= len(self._preds):
            return np.zeros(6, dtype=np.float32)
        r = self._preds.row(self._idx, named=True)
        return np.array(
            [
                r["p_est"],
                r["p_market"],
                r["p_est"] - r["p_market"],
                r.get("confidence", 0.5),
                _DEFAULT_SPREAD,
                _DEFAULT_DAYS,
            ],
            dtype=np.float32,
        )
