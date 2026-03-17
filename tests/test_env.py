"""Test Gymnasium replay environment."""
import polars as pl
import pytest

from snowden.env import SnowdenReplayEnv


@pytest.fixture
def sample_predictions() -> pl.DataFrame:
    return pl.DataFrame({
        "ts": [1, 2, 3, 4, 5],
        "p_est": [0.7, 0.3, 0.8, 0.6, 0.4],
        "p_market": [0.5, 0.5, 0.5, 0.5, 0.5],
        "confidence": [0.8, 0.7, 0.9, 0.6, 0.5],
        "resolved": [True, True, True, True, True],
        "outcome": [1, 0, 1, 0, 1],
    })


class TestSnowdenReplayEnv:
    def test_reset(self, sample_predictions):
        env = SnowdenReplayEnv(sample_predictions, initial_bankroll=2000.0)
        obs, info = env.reset()
        assert obs.shape == (6,)
        assert info == {}

    def test_step_skip(self, sample_predictions):
        env = SnowdenReplayEnv(sample_predictions)
        env.reset()
        obs, reward, done, truncated, info = env.step(0)  # Skip
        assert reward == 0.0
        assert not done
        assert info["bankroll"] == 2000.0

    def test_step_bet(self, sample_predictions):
        env = SnowdenReplayEnv(sample_predictions)
        env.reset()
        obs, reward, done, truncated, info = env.step(1)  # Small bet
        assert isinstance(reward, float)
        assert not done

    def test_episode_completes(self, sample_predictions):
        env = SnowdenReplayEnv(sample_predictions)
        env.reset()
        done = False
        steps = 0
        while not done:
            _, _, done, _, _ = env.step(1)
            steps += 1
        assert steps == len(sample_predictions)

    def test_observation_space(self, sample_predictions):
        env = SnowdenReplayEnv(sample_predictions)
        obs, _ = env.reset()
        assert env.observation_space.contains(obs)

    def test_drawdown_tracking(self, sample_predictions):
        env = SnowdenReplayEnv(sample_predictions)
        env.reset()
        for _ in range(len(sample_predictions)):
            _, _, done, _, info = env.step(3)  # Large bets
            if done:
                break
        assert "drawdown" in info
        assert "peak" in info
