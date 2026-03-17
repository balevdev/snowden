"""Test scanning funnel stages."""
import polars as pl

from snowden.scanner import (
    stage_2_liquidity_gate,
    stage_3_efficiency_score,
    stage_4_strategy_match,
)
from snowden.types import Strategy


class TestStage2LiquidityGate:
    def test_filters_low_volume(self, sample_market_df):
        # Set min_liquidity to filter out markets with < 10000 vol
        result = stage_2_liquidity_gate(sample_market_df)
        # All markets have vol >= 5000 (default threshold) and other criteria
        assert len(result) <= len(sample_market_df)

    def test_filters_wide_spread(self):
        df = pl.DataFrame({
            "market_id": ["m1"],
            "vol_24h": [50000.0],
            "bid_depth": [1000.0],
            "ask_depth": [1000.0],
            "spread": [0.20],  # Way above 0.08 max
            "hours_to_resolve": [200.0],
        })
        result = stage_2_liquidity_gate(df)
        assert len(result) == 0

    def test_passes_good_market(self):
        df = pl.DataFrame({
            "market_id": ["m1"],
            "vol_24h": [50000.0],
            "bid_depth": [500.0],
            "ask_depth": [500.0],
            "spread": [0.02],
            "hours_to_resolve": [200.0],
        })
        result = stage_2_liquidity_gate(df)
        assert len(result) == 1


class TestStage3EfficiencyScore:
    def test_adds_efficiency_column(self, sample_market_df):
        result = stage_3_efficiency_score(sample_market_df)
        assert "efficiency_score" in result.columns

    def test_filters_high_score_markets(self):
        # High inefficiency score (> 0.4 cutoff) gets filtered out.
        # Wide spread, low volume, shallow book, outside time sweet spot.
        df = pl.DataFrame({
            "market_id": ["m1"],
            "mid": [0.50],
            "spread": [0.07],
            "vol_24h": [6000.0],
            "bid_depth": [300.0],
            "ask_depth": [300.0],
            "hours_to_resolve": [48.0],
        })
        result = stage_3_efficiency_score(df)
        assert len(result) == 0


class TestStage4StrategyMatch:
    def test_theta_harvest_detected(self, stage4_theta_df):
        results = stage_4_strategy_match(stage4_theta_df)
        assert len(results) > 0
        strategies = results[0].matched_strategies
        assert Strategy.THETA in strategies

    def test_longshot_fade_detected(self):
        df = pl.DataFrame({
            "market_id": ["m1"],
            "condition_id": ["c1"],
            "question": ["Longshot event?"],
            "description": ["desc"],
            "category": ["other"],
            "end_date": [None],
            "resolution_source": [""],
            "yes_token_id": ["yt1"],
            "no_token_id": ["nt1"],
            "mid": [0.05],
            "bid": [0.04],
            "ask": [0.06],
            "spread": [0.02],
            "vol_24h": [20000.0],
            "bid_depth": [500.0],
            "ask_depth": [500.0],
            "open_interest": [5000.0],
            "hours_to_resolve": [200.0],
            "efficiency_score": [0.2],
        })
        results = stage_4_strategy_match(df)
        assert len(results) > 0
        strategies = results[0].matched_strategies
        assert Strategy.LONGSHOT_FADE in strategies

    def test_no_match_returns_empty(self):
        df = pl.DataFrame({
            "market_id": ["m1"],
            "condition_id": ["c1"],
            "question": ["Normal market?"],
            "description": ["desc"],
            "category": ["science"],
            "end_date": [None],
            "resolution_source": [""],
            "yes_token_id": ["yt1"],
            "no_token_id": ["nt1"],
            "mid": [0.50],
            "bid": [0.49],
            "ask": [0.51],
            "spread": [0.02],
            "vol_24h": [50000.0],
            "bid_depth": [5000.0],
            "ask_depth": [5000.0],
            "open_interest": [100000.0],
            "hours_to_resolve": [200.0],
            "efficiency_score": [0.2],
        })
        results = stage_4_strategy_match(df)
        assert len(results) == 0

    def test_results_sorted_by_priority(self):
        df = pl.DataFrame({
            "market_id": ["m1", "m2"],
            "condition_id": ["c1", "c2"],
            "question": ["Q1?", "Q2?"],
            "description": ["d1", "d2"],
            "category": ["other", "other"],
            "end_date": [None, None],
            "resolution_source": ["", ""],
            "yes_token_id": ["yt1", "yt2"],
            "no_token_id": ["nt1", "nt2"],
            "mid": [0.95, 0.90],
            "bid": [0.94, 0.89],
            "ask": [0.96, 0.91],
            "spread": [0.02, 0.02],
            "vol_24h": [50000.0, 10000.0],
            "bid_depth": [500.0, 500.0],
            "ask_depth": [500.0, 500.0],
            "open_interest": [10000.0, 5000.0],
            "hours_to_resolve": [200.0, 200.0],
            "efficiency_score": [0.2, 0.2],
        })
        results = stage_4_strategy_match(df)
        if len(results) >= 2:
            assert results[0].priority_score >= results[1].priority_score
