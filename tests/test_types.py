"""Test Pydantic model validation."""
from datetime import UTC, datetime

import pytest

from snowden.types import (
    CalibrationReport,
    MarketCategory,
    MarketSnapshot,
    OrderResult,
    Regime,
    RiskCheck,
    ScanResult,
    Strategy,
    TradeSignal,
)


class TestEnums:
    def test_regime_values(self):
        assert Regime.CONSENSUS == "consensus"
        assert Regime.CONTESTED == "contested"
        assert Regime.CATALYST == "catalyst_pending"
        assert len(Regime) == 6

    def test_strategy_values(self):
        assert Strategy.THETA == "theta_harvest"
        assert Strategy.LONGSHOT_FADE == "longshot_fade"
        assert len(Strategy) == 6

    def test_category_values(self):
        assert MarketCategory.POLITICS_US == "politics_us"
        assert len(MarketCategory) == 9


class TestMarketSnapshot:
    def test_valid_snapshot(self, sample_snapshot):
        assert sample_snapshot.market_id == "test_m1"
        assert sample_snapshot.mid == 0.50

    def test_defaults(self):
        s = MarketSnapshot(
            market_id="x",
            condition_id="c",
            question="q",
            description="d",
            yes_token_id="y",
            no_token_id="n",
            mid=0.5,
            bid=0.49,
            ask=0.51,
            spread=0.02,
            vol_24h=1000,
            bid_depth=100,
            ask_depth=100,
        )
        assert s.category == MarketCategory.OTHER
        assert s.active is True
        assert s.efficiency_score == 0.0


class TestScanResult:
    def test_defaults(self, sample_snapshot):
        sr = ScanResult(
            market=sample_snapshot,
            matched_strategies=[Strategy.THETA],
            priority_score=1.0,
        )
        assert sr.suggested_direction == "UNCLEAR"
        assert sr.news_headlines == []
        assert sr.price_history_7d == []


class TestTradeSignal:
    def test_valid_signal(self, sample_signal):
        assert sample_signal.direction == "YES"
        assert sample_signal.size_usd == 100.0

    def test_direction_literal(self):
        with pytest.raises(ValueError):
            TradeSignal(
                market_id="x",
                token_id="t",
                direction="MAYBE",
                p_est=0.5,
                p_market=0.5,
                confidence=0.5,
                kelly_frac=0.05,
                size_usd=10,
                strategy=Strategy.THETA,
                edge=0.0,
            )


class TestOrderResult:
    def test_valid_statuses(self):
        for status in ["FILLED", "PARTIAL", "CANCELLED", "PAPER", "REJECTED"]:
            r = OrderResult(status=status, ts=datetime.now(UTC))
            assert r.status == status


class TestRiskCheck:
    def test_approved(self):
        rc = RiskCheck(
            approved=True, heat=0.5, drawdown=0.02,
            single_exposure=0.1, correlated_exposure=0.2,
        )
        assert rc.approved
        assert rc.reason is None


class TestCalibrationReport:
    def test_valid_report(self):
        r = CalibrationReport(
            brier_score=0.15,
            n_predictions=100,
            n_resolved=80,
            overconfidence_bias=0.02,
            underconfidence_bias=0.01,
            reliability_buckets={},
            platt_fitted=True,
            timestamp=datetime.now(UTC),
        )
        assert r.brier_score == 0.15
