"""
snowden/kelly.py

Kelly criterion for binary prediction markets.
Quarter-Kelly by default for safety. All math in NumPy.
"""
from __future__ import annotations

from typing import Literal

import numpy as np

from snowden.config import settings
from snowden.types import Strategy, TradeSignal


def kelly_fraction(
    p_est: float,
    p_market: float,
    divisor: float | None = None,
    max_frac: float | None = None,
) -> float | None:
    """
    Compute Kelly fraction for a binary market.
    Returns None if no edge or negative Kelly.
    """
    divisor = divisor or settings.kelly_divisor
    max_frac = max_frac or settings.max_single_position

    if abs(p_est - p_market) < settings.kelly_edge_threshold:
        return None

    if p_est > p_market:
        # Buying YES
        b = (1.0 / p_market) - 1.0  # odds
        f = (p_est * b - (1 - p_est)) / b
    else:
        # Buying NO
        p_no_market = 1.0 - p_market
        p_no_est = 1.0 - p_est
        b = (1.0 / p_no_market) - 1.0
        f = (p_no_est * b - p_est) / b

    if f <= 0:
        return None

    return float(np.clip(f / divisor, 0.0, max_frac))


def compute_size(
    p_est: float,
    p_market: float,
    bankroll: float,
    divisor: float | None = None,
    max_frac: float | None = None,
    min_usd: float | None = None,
) -> float | None:
    """Compute position size in USD. Returns None if no trade."""
    min_usd = min_usd or settings.min_trade_usd
    frac = kelly_fraction(p_est, p_market, divisor, max_frac)
    if frac is None:
        return None
    size = frac * bankroll
    return size if size >= min_usd else None


def build_signal(
    market_id: str,
    yes_token: str,
    no_token: str,
    p_est: float,
    p_market: float,
    confidence: float,
    bankroll: float,
    strategy: Strategy,
) -> TradeSignal | None:
    """Build a typed trade signal if edge exceeds threshold."""
    edge = abs(p_est - p_market) * confidence
    if edge < settings.edge_threshold:
        return None

    going_yes = p_est > p_market
    effective_p_est = p_est if going_yes else 1.0 - p_est
    effective_p_market = p_market if going_yes else 1.0 - p_market

    size = compute_size(effective_p_est, effective_p_market, bankroll)
    if size is None:
        return None

    frac = size / bankroll
    token_id = yes_token if going_yes else no_token
    direction: Literal["YES", "NO"] = "YES" if going_yes else "NO"
    limit_price = effective_p_market + settings.slippage_buffer

    return TradeSignal(
        market_id=market_id,
        token_id=token_id,
        direction=direction,
        p_est=p_est,
        p_market=p_market,
        confidence=confidence,
        kelly_frac=frac,
        size_usd=round(size, 2),
        strategy=strategy,
        edge=round(p_est - p_market, 4),
        limit_price=round(limit_price, 2),
    )
