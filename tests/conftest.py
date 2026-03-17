"""Shared fixtures for Snowden tests."""
from datetime import UTC, datetime

import polars as pl
import pytest

from snowden.types import (
    EventAnalysis,
    MarketCategory,
    MarketSnapshot,
    PortfolioState,
    Position,
    Regime,
    ScanResult,
    Strategy,
    TradeSignal,
)


@pytest.fixture
def sample_market_df() -> pl.DataFrame:
    """DataFrame mimicking raw market data from Gamma API."""
    return pl.DataFrame(
        {
            "market_id": ["m1", "m2", "m3", "m4", "m5"],
            "condition_id": ["c1", "c2", "c3", "c4", "c5"],
            "question": [
                "Will Trump win 2024?",
                "Will Bitcoin hit 100k?",
                "Will it rain tomorrow?",
                "Will the Fed cut rates?",
                "Will team X win?",
            ],
            "description": ["desc1", "desc2", "desc3", "desc4", "desc5"],
            "category": [
                "politics_us",
                "crypto",
                "other",
                "finance",
                "sports",
            ],
            "end_date": [None] * 5,
            "resolution_source": [""] * 5,
            "yes_token_id": ["yt1", "yt2", "yt3", "yt4", "yt5"],
            "no_token_id": ["nt1", "nt2", "nt3", "nt4", "nt5"],
            "mid": [0.55, 0.92, 0.50, 0.30, 0.05],
            "bid": [0.54, 0.91, 0.49, 0.29, 0.04],
            "ask": [0.56, 0.93, 0.51, 0.31, 0.06],
            "spread": [0.02, 0.02, 0.02, 0.02, 0.02],
            "vol_24h": [50000.0, 30000.0, 8000.0, 15000.0, 6000.0],
            "bid_depth": [1000.0, 500.0, 300.0, 400.0, 250.0],
            "ask_depth": [1000.0, 500.0, 300.0, 400.0, 250.0],
            "open_interest": [100000.0, 50000.0, 5000.0, 20000.0, 3000.0],
            "hours_to_resolve": [500.0, 200.0, 48.0, 336.0, 72.0],
        }
    )


@pytest.fixture
def stage4_theta_df() -> pl.DataFrame:
    """DataFrame with one theta-eligible market."""
    return pl.DataFrame({
        "market_id": ["m1"], "condition_id": ["c1"],
        "question": ["Will X happen?"], "description": ["desc"],
        "category": ["other"], "end_date": [None], "resolution_source": [""],
        "yes_token_id": ["yt1"], "no_token_id": ["nt1"],
        "mid": [0.92], "bid": [0.91], "ask": [0.93], "spread": [0.02],
        "vol_24h": [30000.0], "bid_depth": [500.0], "ask_depth": [500.0],
        "open_interest": [10000.0], "hours_to_resolve": [200.0],
        "efficiency_score": [0.2],
    })


@pytest.fixture
def sample_snapshot() -> MarketSnapshot:
    return MarketSnapshot(
        market_id="test_m1",
        condition_id="test_c1",
        question="Will it rain?",
        description="Test market",
        category=MarketCategory.OTHER,
        yes_token_id="yt1",
        no_token_id="nt1",
        mid=0.50,
        bid=0.49,
        ask=0.51,
        spread=0.02,
        vol_24h=10000.0,
        bid_depth=500.0,
        ask_depth=500.0,
        hours_to_resolve=200.0,
    )


@pytest.fixture
def sample_scan_result(sample_snapshot: MarketSnapshot) -> ScanResult:
    return ScanResult(
        market=sample_snapshot,
        matched_strategies=[Strategy.STALE_REPRICE],
        priority_score=0.5,
    )


@pytest.fixture
def sample_analysis() -> EventAnalysis:
    return EventAnalysis(
        market_id="test_m1",
        question="Will it rain?",
        p_market=0.50,
        p_est=0.65,
        p_est_raw=0.63,
        confidence=0.8,
        regime=Regime.CONTESTED,
        edge=0.15,
        reasoning="Strong evidence for rain.",
        key_factors=["Weather data", "Historical patterns"],
        data_quality=0.7,
        strategy_hint=Strategy.STALE_REPRICE,
    )


@pytest.fixture
def sample_signal() -> TradeSignal:
    return TradeSignal(
        market_id="test_m1",
        token_id="yt1",
        direction="YES",
        p_est=0.65,
        p_market=0.50,
        confidence=0.8,
        kelly_frac=0.05,
        size_usd=100.0,
        strategy=Strategy.STALE_REPRICE,
        edge=0.15,
        limit_price=0.51,
    )


@pytest.fixture
def sample_portfolio() -> PortfolioState:
    return PortfolioState(
        bankroll=1800.0,
        total_equity=2000.0,
        positions=[
            Position(
                market_id="existing_1",
                token_id="et1",
                direction="YES",
                size_usd=200.0,
                avg_price=0.40,
                current_mid=0.45,
                unrealized_pnl=25.0,
                category=MarketCategory.POLITICS_US,
                strategy=Strategy.PARTISAN_FADE,
                opened_at=datetime(2024, 1, 1, tzinfo=UTC),
            )
        ],
        heat=0.10,
        daily_pnl=50.0,
        daily_drawdown=0.02,
        realized_pnl_total=100.0,
        trade_count_today=3,
        cycle_number=10,
    )
