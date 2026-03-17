"""Test agent modules."""
from datetime import UTC, datetime

from snowden.agents.sentinel import check_kill_switch, check_signal
from snowden.types import (
    MarketCategory,
    PortfolioState,
    Position,
    Strategy,
    TradeSignal,
)


class TestSentinel:
    def test_approve_normal_signal(self, sample_signal, sample_portfolio):
        result = check_signal(sample_signal, sample_portfolio)
        assert result.approved

    def test_reject_oversized_position(self, sample_portfolio):
        big_signal = TradeSignal(
            market_id="m1",
            token_id="yt1",
            direction="YES",
            p_est=0.7,
            p_market=0.5,
            confidence=0.8,
            kelly_frac=0.30,
            size_usd=600.0,  # 30% of 2000 equity
            strategy=Strategy.THETA,
            edge=0.2,
            limit_price=0.51,
        )
        result = check_signal(big_signal, sample_portfolio)
        assert not result.approved
        assert "Single position" in (result.reason or "")

    def test_reject_high_heat(self, sample_signal):
        hot_portfolio = PortfolioState(
            bankroll=200.0,
            total_equity=2000.0,
            positions=[],
            heat=0.78,
            daily_pnl=0.0,
            daily_drawdown=0.0,
            realized_pnl_total=0.0,
            trade_count_today=0,
            cycle_number=1,
        )
        result = check_signal(sample_signal, hot_portfolio)
        # heat is 0.78 + 100/2000 = 0.83 > 0.80
        assert not result.approved

    def test_reject_drawdown_exceeded(self, sample_signal):
        dd_portfolio = PortfolioState(
            bankroll=1800.0,
            total_equity=2000.0,
            positions=[],
            heat=0.10,
            daily_pnl=-250.0,
            daily_drawdown=0.12,  # > 0.10 max
            realized_pnl_total=-250.0,
            trade_count_today=5,
            cycle_number=1,
        )
        result = check_signal(sample_signal, dd_portfolio)
        assert not result.approved
        assert "drawdown" in (result.reason or "").lower()

    def test_reject_correlated_exposure(self):
        """Sentinel blocks when same-category exposure exceeds limit."""
        # Portfolio with existing POLITICS_US position totaling >40% equity
        portfolio = PortfolioState(
            bankroll=1000.0,
            total_equity=2000.0,
            positions=[
                Position(
                    market_id="pol_1",
                    token_id="pt1",
                    direction="YES",
                    size_usd=500.0,
                    avg_price=0.50,
                    current_mid=0.55,
                    unrealized_pnl=50.0,
                    category=MarketCategory.POLITICS_US,
                    strategy=Strategy.PARTISAN_FADE,
                    opened_at=datetime(2024, 1, 1, tzinfo=UTC),
                ),
                Position(
                    market_id="pol_2",
                    token_id="pt2",
                    direction="YES",
                    size_usd=400.0,
                    avg_price=0.60,
                    current_mid=0.65,
                    unrealized_pnl=30.0,
                    category=MarketCategory.POLITICS_US,
                    strategy=Strategy.PARTISAN_FADE,
                    opened_at=datetime(2024, 1, 1, tzinfo=UTC),
                ),
            ],
            heat=0.20,
            daily_pnl=0.0,
            daily_drawdown=0.0,
            realized_pnl_total=0.0,
            trade_count_today=1,
            cycle_number=5,
        )
        # New signal also in POLITICS_US
        signal = TradeSignal(
            market_id="pol_3",
            token_id="pt3",
            direction="YES",
            p_est=0.70,
            p_market=0.55,
            confidence=0.8,
            kelly_frac=0.05,
            size_usd=100.0,
            strategy=Strategy.PARTISAN_FADE,
            edge=0.15,
            limit_price=0.56,
            category=MarketCategory.POLITICS_US,
        )
        result = check_signal(signal, portfolio)
        # correlated = (500 + 400 + 100) / 2000 = 0.50 > 0.40
        assert not result.approved
        assert "Correlated" in (result.reason or "")


class TestKillSwitch:
    def test_no_kill_normal(self, sample_portfolio):
        assert not check_kill_switch(sample_portfolio)

    def test_kill_on_drawdown(self):
        portfolio = PortfolioState(
            bankroll=1600.0,
            total_equity=1800.0,
            positions=[],
            heat=0.10,
            daily_pnl=-300.0,
            daily_drawdown=0.15,
            realized_pnl_total=-300.0,
            trade_count_today=5,
            cycle_number=1,
        )
        assert check_kill_switch(portfolio)
