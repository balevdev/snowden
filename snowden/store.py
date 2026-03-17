"""
snowden/store.py

TimescaleDB persistence layer. asyncpg for writes, Polars for reads.
All queries use parameterized statements. No raw string interpolation.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import asyncpg
import polars as pl

from snowden.config import settings

if TYPE_CHECKING:
    from snowden.types import (
        EventAnalysis,
        MarketSnapshot,
        OrderResult,
        PortfolioState,
        TradeSignal,
    )


class Store:
    def __init__(self) -> None:
        self._pool: asyncpg.Pool | None = None

    def _ensure_pool(self) -> asyncpg.Pool:
        if not self._pool:
            raise RuntimeError("Store not connected. Call connect() first.")
        return self._pool

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(
            dsn=settings.tsdb_dsn,
            min_size=2,
            max_size=10,
        )

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()

    async def log_tick(self, s: MarketSnapshot) -> None:
        pool = self._ensure_pool()
        await pool.execute(
            """INSERT INTO market_ticks
               (ts, token_id, market_id, mid, spread, vol_24h, bid_depth, ask_depth)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
            datetime.now(UTC),
            s.yes_token_id,
            s.market_id,
            s.mid,
            s.spread,
            s.vol_24h,
            s.bid_depth,
            s.ask_depth,
        )

    async def log_prediction(self, a: EventAnalysis) -> None:
        pool = self._ensure_pool()
        await pool.execute(
            """INSERT INTO predictions
               (ts, market_id, question, p_market, p_est, p_est_raw, confidence,
                regime, strategy, edge, reasoning, data_quality)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)""",
            datetime.now(UTC),
            a.market_id,
            a.question,
            a.p_market,
            a.p_est,
            a.p_est_raw,
            a.confidence,
            a.regime.value,
            a.strategy_hint.value if a.strategy_hint else None,
            a.edge,
            a.reasoning,
            a.data_quality,
        )

    async def log_trade(
        self, signal: TradeSignal, result: OrderResult, paper: bool
    ) -> None:
        pool = self._ensure_pool()
        await pool.execute(
            """INSERT INTO trades
               (ts, market_id, token_id, side, direction, size, price,
                order_id, status, strategy, paper, kelly_frac, edge)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)""",
            result.ts,
            signal.market_id,
            signal.token_id,
            "BUY",
            signal.direction,
            signal.size_usd,
            result.fill_price,
            result.order_id,
            result.status,
            signal.strategy.value,
            paper,
            signal.kelly_frac,
            signal.edge,
        )

    async def log_portfolio_snapshot(self, state: PortfolioState) -> None:
        pool = self._ensure_pool()
        await pool.execute(
            """INSERT INTO portfolio_snapshots
               (ts, bankroll, total_equity, heat, daily_pnl,
                daily_drawdown, position_count, cycle_number)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8)""",
            datetime.now(UTC),
            state.bankroll,
            state.total_equity,
            state.heat,
            state.daily_pnl,
            state.daily_drawdown,
            len(state.positions),
            state.cycle_number,
        )

    async def log_scan_metrics(
        self, stage_counts: dict[str, int], duration_ms: float
    ) -> None:
        pool = self._ensure_pool()
        await pool.execute(
            """INSERT INTO scanner_metrics
               (ts, stage_1, stage_2, stage_3, stage_4, stage_5, duration_ms)
               VALUES ($1,$2,$3,$4,$5,$6,$7)""",
            datetime.now(UTC),
            stage_counts.get("stage_1", 0),
            stage_counts.get("stage_2", 0),
            stage_counts.get("stage_3", 0),
            stage_counts.get("stage_4", 0),
            stage_counts.get("stage_5", 0),
            duration_ms,
        )

    async def get_resolved_predictions(self) -> pl.DataFrame:
        pool = self._ensure_pool()
        rows = await pool.fetch(
            "SELECT p_est, p_est_raw, outcome, regime, strategy "
            "FROM predictions WHERE resolved = true"
        )
        return pl.DataFrame([dict(r) for r in rows])

    async def get_recent_predictions(
        self, market_id: str, hours: int = 24
    ) -> pl.DataFrame:
        pool = self._ensure_pool()
        rows = await pool.fetch(
            "SELECT * FROM predictions "
            "WHERE market_id = $1 AND ts > NOW() - make_interval(hours => $2) "
            "ORDER BY ts DESC",
            market_id,
            hours,
        )
        return pl.DataFrame([dict(r) for r in rows])

    async def get_daily_trades(self) -> pl.DataFrame:
        pool = self._ensure_pool()
        rows = await pool.fetch(
            "SELECT * FROM trades WHERE ts > NOW() - INTERVAL '24 hours' ORDER BY ts DESC"
        )
        return pl.DataFrame([dict(r) for r in rows])

    async def get_active_positions(self) -> pl.DataFrame:
        """Get positions that haven't been closed or resolved."""
        pool = self._ensure_pool()
        rows = await pool.fetch(
            """SELECT t.market_id, t.token_id, t.direction, t.size, t.price,
                      t.strategy, t.ts as opened_at
               FROM trades t
               WHERE t.status IN ('FILLED', 'PAPER')
               AND NOT EXISTS (
                   SELECT 1 FROM trades t2
                   WHERE t2.market_id = t.market_id
                   AND t2.side = 'SELL'
                   AND t2.ts > t.ts
               )
               ORDER BY t.ts DESC"""
        )
        return pl.DataFrame([dict(r) for r in rows])

    async def mark_resolved(self, market_id: str, outcome: int) -> None:
        """Backfill resolution outcome for a market."""
        pool = self._ensure_pool()
        await pool.execute(
            "UPDATE predictions SET resolved = true, outcome = $1 WHERE market_id = $2",
            outcome,
            market_id,
        )
