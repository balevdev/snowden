"""
snowden/types.py

All Pydantic models, enums, and Protocol interfaces.
Single source of truth for every data shape in the system.
"""
from __future__ import annotations

from datetime import datetime  # noqa: TCH003
from enum import StrEnum
from typing import Any, Literal, Protocol, runtime_checkable

import polars as pl  # noqa: TCH002
from pydantic import BaseModel, Field

# ── Enums ──────────────────────────────────────────────────────────

class Regime(StrEnum):
    """Market regime classification for strategy selection."""
    CONSENSUS = "consensus"
    CONTESTED = "contested"
    CATALYST = "catalyst_pending"
    RESOLVING = "resolution_imminent"
    STALE = "stale"
    NEWS_DRIVEN = "news_driven"


class Strategy(StrEnum):
    """Trading strategy labels. Maps to edge sources."""
    THETA = "theta_harvest"
    LONGSHOT_FADE = "longshot_fade"
    NEWS_LATENCY = "news_latency"
    PARTISAN_FADE = "partisan_fade"
    CORRELATED_ARB = "correlated_arb"
    STALE_REPRICE = "stale_reprice"


class MarketCategory(StrEnum):
    """Broad market categories for correlation tracking."""
    POLITICS_US = "politics_us"
    POLITICS_INTL = "politics_intl"
    CRYPTO = "crypto"
    FINANCE = "finance"
    SPORTS = "sports"
    SCIENCE = "science"
    CULTURE = "culture"
    LEGAL = "legal"
    OTHER = "other"


# ── Scanner Models ──────────────────────────────────────────────────

class MarketSnapshot(BaseModel):
    """Raw market data from Gamma + CLOB APIs. One per active market."""
    market_id: str
    condition_id: str
    question: str
    description: str
    category: MarketCategory = MarketCategory.OTHER
    end_date: datetime | None = None
    resolution_source: str = ""
    active: bool = True

    # Token info
    yes_token_id: str
    no_token_id: str

    # Price data
    mid: float
    bid: float
    ask: float
    spread: float
    vol_24h: float
    bid_depth: float
    ask_depth: float
    open_interest: float = 0.0

    # Computed in scanner
    hours_to_resolve: float | None = None
    efficiency_score: float = 0.0
    opportunity_score: float = 0.0


class ScanResult(BaseModel):
    """Output of the scanning funnel. Passed to Analyst for deep analysis."""
    market: MarketSnapshot
    matched_strategies: list[Strategy]
    priority_score: float
    news_headlines: list[str] = Field(default_factory=list)
    price_history_7d: list[float] = Field(default_factory=list)
    suggested_direction: Literal["YES", "NO", "UNCLEAR"] = "UNCLEAR"
    pre_screen_reasoning: str = ""


# ── Analyst Models ──────────────────────────────────────────────────

class EventAnalysis(BaseModel):
    """Analyst output. Probability estimate + metadata."""
    market_id: str
    question: str
    p_market: float
    p_est: float
    p_est_raw: float
    confidence: float
    regime: Regime
    edge: float
    reasoning: str
    key_factors: list[str] = Field(default_factory=list)
    data_quality: float = 0.5
    strategy_hint: Strategy | None = None


# ── Trading Models ──────────────────────────────────────────────────

class TradeSignal(BaseModel):
    """Sized trade signal from Kelly criterion."""
    market_id: str
    token_id: str
    direction: Literal["YES", "NO"]
    p_est: float
    p_market: float
    confidence: float
    kelly_frac: float
    size_usd: float
    strategy: Strategy
    edge: float
    category: MarketCategory = MarketCategory.OTHER
    limit_price: float | None = None


class RiskCheck(BaseModel):
    """Sentinel output. Approve or veto a trade signal."""
    approved: bool
    reason: str | None = None
    heat: float
    drawdown: float
    single_exposure: float
    correlated_exposure: float


class OrderResult(BaseModel):
    """Execution result from Trader."""
    status: Literal["FILLED", "PARTIAL", "CANCELLED", "PAPER", "REJECTED"]
    order_id: str | None = None
    fill_price: float | None = None
    fill_size: float | None = None
    slippage: float | None = None
    ts: datetime


# ── Portfolio Models ────────────────────────────────────────────────

class Position(BaseModel):
    """An open position in the portfolio."""
    market_id: str
    token_id: str
    direction: Literal["YES", "NO"]
    size_usd: float
    avg_price: float
    current_mid: float
    unrealized_pnl: float
    category: MarketCategory
    strategy: Strategy
    opened_at: datetime


class PortfolioState(BaseModel):
    """Complete portfolio snapshot. Maintained by Chief."""
    bankroll: float
    total_equity: float
    positions: list[Position]
    heat: float
    daily_pnl: float
    daily_drawdown: float
    realized_pnl_total: float
    trade_count_today: int
    cycle_number: int


# ── Calibration Models ──────────────────────────────────────────────

class CalibrationReport(BaseModel):
    """Output of calibration analysis."""
    brier_score: float
    n_predictions: int
    n_resolved: int
    overconfidence_bias: float
    underconfidence_bias: float
    reliability_buckets: dict[str, dict[str, float]]
    platt_fitted: bool
    timestamp: datetime


# ── Protocol Interfaces ─────────────────────────────────────────────

@runtime_checkable
class MarketClient(Protocol):
    """Interface for market data + execution. Swappable Live/Sim backends."""
    async def get_active_markets(self) -> pl.DataFrame: ...
    async def get_book(self, token_id: str) -> dict[str, Any]: ...
    async def get_midpoint(self, token_id: str) -> float: ...
    async def get_price_history(self, token_id: str, days: int) -> pl.DataFrame: ...
    async def get_market_detail(self, market_id: str) -> dict[str, Any]: ...
    async def execute(self, signal: TradeSignal) -> OrderResult: ...


@runtime_checkable
class DataStore(Protocol):
    """Interface for persistence. Keeps agent code DB-agnostic in tests."""
    async def log_tick(self, snapshot: MarketSnapshot) -> None: ...
    async def log_prediction(self, analysis: EventAnalysis) -> None: ...
    async def log_trade(self, signal: TradeSignal, result: OrderResult, paper: bool) -> None: ...
    async def log_portfolio_snapshot(self, state: PortfolioState) -> None: ...
    async def get_resolved_predictions(self) -> pl.DataFrame: ...
    async def get_recent_predictions(self, market_id: str, hours: int) -> pl.DataFrame: ...
    async def get_open_positions(self) -> list[Position]: ...
    async def get_daily_trades(self) -> pl.DataFrame: ...
