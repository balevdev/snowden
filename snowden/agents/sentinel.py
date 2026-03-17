"""
snowden/agents/sentinel.py

Risk monitoring agent. Runs on a fast heartbeat (every 1 min).
Checks portfolio limits. Can veto trades and freeze the system.
Pure math for most checks. Haiku for anomaly detection.
"""
from __future__ import annotations

import structlog

from snowden.config import settings
from snowden.types import PortfolioState, RiskCheck, TradeSignal

log = structlog.get_logger()


def check_signal(
    signal: TradeSignal,
    portfolio: PortfolioState,
) -> RiskCheck:
    """Evaluate a trade signal against risk limits."""
    # Single position size check
    single_exposure = (
        signal.size_usd / portfolio.total_equity
        if portfolio.total_equity > 0
        else 1.0
    )
    if single_exposure > settings.max_single_position:
        return RiskCheck(
            approved=False,
            reason=(
                f"Single position {single_exposure:.1%} exceeds "
                f"limit {settings.max_single_position:.0%}"
            ),
            heat=portfolio.heat,
            drawdown=portfolio.daily_drawdown,
            single_exposure=single_exposure,
            correlated_exposure=0.0,
        )

    # Portfolio heat check
    new_heat = (
        (portfolio.heat * portfolio.total_equity + signal.size_usd)
        / portfolio.total_equity
        if portfolio.total_equity > 0
        else 1.0
    )
    if new_heat > settings.max_heat:
        return RiskCheck(
            approved=False,
            reason=(
                f"Portfolio heat {new_heat:.1%} would exceed "
                f"limit {settings.max_heat:.0%}"
            ),
            heat=portfolio.heat,
            drawdown=portfolio.daily_drawdown,
            single_exposure=single_exposure,
            correlated_exposure=0.0,
        )

    # Daily drawdown check
    if portfolio.daily_drawdown > settings.max_daily_drawdown:
        return RiskCheck(
            approved=False,
            reason=(
                f"Daily drawdown {portfolio.daily_drawdown:.1%} exceeds "
                f"limit {settings.max_daily_drawdown:.0%}. FROZEN."
            ),
            heat=portfolio.heat,
            drawdown=portfolio.daily_drawdown,
            single_exposure=single_exposure,
            correlated_exposure=0.0,
        )

    # Correlated exposure check
    signal_category = signal.category.value
    correlated_usd = sum(
        p.size_usd
        for p in portfolio.positions
        if p.category.value == signal_category
    )
    correlated_exposure = (
        (correlated_usd + signal.size_usd) / portfolio.total_equity
        if portfolio.total_equity > 0
        else 0.0
    )
    if correlated_exposure > settings.max_correlated:
        return RiskCheck(
            approved=False,
            reason=(
                f"Correlated exposure ({signal_category}) at "
                f"{correlated_exposure:.1%} exceeds {settings.max_correlated:.0%}"
            ),
            heat=portfolio.heat,
            drawdown=portfolio.daily_drawdown,
            single_exposure=single_exposure,
            correlated_exposure=correlated_exposure,
        )

    # All checks passed
    return RiskCheck(
        approved=True,
        heat=new_heat,
        drawdown=portfolio.daily_drawdown,
        single_exposure=single_exposure,
        correlated_exposure=correlated_exposure,
    )


def check_kill_switch(portfolio: PortfolioState) -> bool:
    """Returns True if trading should be frozen."""
    if portfolio.daily_drawdown > settings.max_daily_drawdown:
        log.critical("KILL_SWITCH", drawdown=portfolio.daily_drawdown)
        return True
    return False
