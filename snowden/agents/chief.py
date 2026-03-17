"""
snowden/agents/chief.py

Orchestrator agent. Runs the complete trading cycle.
Manages portfolio state. Dispatches to Analyst, Sentinel, Trader.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

import anthropic
import structlog

from snowden.agents.analyst import analyze_batch
from snowden.agents.sentinel import check_kill_switch, check_signal
from snowden.agents.trader import execute_signal
from snowden.calibrate import Calibrator
from snowden.config import settings
from snowden.kelly import build_signal
from snowden.scanner import (
    stage_2_liquidity_gate,
    stage_3_efficiency_score,
    stage_4_strategy_match,
    stage_5_haiku_triage,
)
from snowden.types import MarketCategory, PortfolioState, Position, ScanResult, Strategy

if TYPE_CHECKING:
    import polars as pl

    from snowden.market import LiveClient, SimClient
    from snowden.store import Store

log = structlog.get_logger()


class Chief:
    def __init__(self, client: LiveClient | SimClient, store: Store) -> None:
        self._client = client
        self._store = store
        self._calibrator = Calibrator()
        self._anthropic = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._portfolio = PortfolioState(
            bankroll=settings.bankroll,
            total_equity=settings.bankroll,
            positions=[],
            heat=0.0,
            daily_pnl=0.0,
            daily_drawdown=0.0,
            realized_pnl_total=0.0,
            trade_count_today=0,
            cycle_number=0,
        )

    @staticmethod
    def _build_positions(df: pl.DataFrame) -> list[Position]:
        if df.is_empty():
            return []
        return [
            Position(
                market_id=row["market_id"],
                token_id=row["token_id"],
                direction=row["direction"],
                size_usd=row["size"],
                avg_price=row["price"],
                current_mid=row["price"],
                unrealized_pnl=0.0,
                category=MarketCategory.OTHER,
                strategy=Strategy(row["strategy"]) if row["strategy"] else Strategy.THETA,
                opened_at=row["opened_at"],
            )
            for row in df.iter_rows(named=True)
        ]

    async def initialize(self) -> None:
        """Load calibrator and restore portfolio state."""
        await self._calibrator.fit_from_db(self._store)
        positions_df = await self._store.get_active_positions()
        self._portfolio.positions = self._build_positions(positions_df)
        log.info("chief_initialized", calibrator_fitted=self._calibrator.is_fitted)

    async def _scan(self) -> tuple[list[ScanResult], dict[str, int], float]:
        """Run scanning stages 1-5."""
        t0 = time.monotonic()
        raw_df = await self._client.get_active_markets()
        stage_counts = {"stage_1": len(raw_df)}
        filtered = stage_2_liquidity_gate(raw_df)
        stage_counts["stage_2"] = len(filtered)
        scored = stage_3_efficiency_score(filtered)
        stage_counts["stage_3"] = len(scored)
        candidates = stage_4_strategy_match(scored)
        stage_counts["stage_4"] = len(candidates)
        approved = await stage_5_haiku_triage(candidates, self._anthropic)
        stage_counts["stage_5"] = len(approved)
        duration_ms = (time.monotonic() - t0) * 1000
        return approved, stage_counts, duration_ms

    async def run_cycle(self, cycle_number: int) -> None:
        """Execute one complete trading cycle."""
        self._portfolio.cycle_number = cycle_number

        # Reload positions from DB
        positions_df = await self._store.get_active_positions()
        self._portfolio.positions = self._build_positions(positions_df)

        # Kill switch check
        if check_kill_switch(self._portfolio):
            log.critical("FROZEN", reason="kill_switch_active")
            return

        # Scan
        approved, stage_counts, scan_ms = await self._scan()
        await self._store.log_scan_metrics(stage_counts, scan_ms)
        log.info("scan_complete", stages=stage_counts, duration_ms=round(scan_ms))

        if not approved:
            log.info("no_opportunities")
            return

        # Enrich with price history
        for scan in approved:
            try:
                history = await self._client.get_price_history(
                    scan.market.yes_token_id, days=7
                )
                if len(history) > 0:
                    scan.price_history_7d = history["price"].to_list()[-7:]
            except Exception:
                pass

        # ANALYST: Deep analysis
        analyses = await analyze_batch(approved, self._calibrator)
        log.info("analyst_complete", count=len(analyses))

        # Build signals, risk-check, execute
        executed = 0
        for analysis in analyses:
            if analysis.confidence < settings.min_confidence:
                continue

            # Find the scan result for token IDs
            matched_scan = next(
                (s for s in approved if s.market.market_id == analysis.market_id),
                None,
            )
            if matched_scan is None:
                continue

            strategy = analysis.strategy_hint or (
                matched_scan.matched_strategies[0]
                if matched_scan.matched_strategies
                else Strategy.THETA
            )

            signal = build_signal(
                market_id=analysis.market_id,
                yes_token=matched_scan.market.yes_token_id,
                no_token=matched_scan.market.no_token_id,
                p_est=analysis.p_est,
                p_market=analysis.p_market,
                confidence=analysis.confidence,
                bankroll=self._portfolio.bankroll,
                strategy=strategy,
            )
            if signal is None:
                continue

            # Pass category to signal
            signal.category = matched_scan.market.category

            # Sentinel risk check
            risk = check_signal(signal, self._portfolio)
            log.info(
                "risk_check",
                market_id=signal.market_id,
                approved=risk.approved,
                reason=risk.reason,
            )

            if not risk.approved:
                continue

            # Execute
            result = await execute_signal(signal, self._client, self._store)
            log.info(
                "execution_result",
                market_id=signal.market_id,
                status=result.status,
            )

            if result.status in ("FILLED", "PAPER"):
                executed += 1
                self._portfolio.bankroll -= signal.size_usd
                self._portfolio.heat = risk.heat
                self._portfolio.trade_count_today += 1

            # Log prediction
            await self._store.log_prediction(analysis)

        # Snapshot portfolio
        position_value = sum(
            p.size_usd * (p.current_mid / p.avg_price)
            for p in self._portfolio.positions
        ) if self._portfolio.positions else 0.0
        self._portfolio.total_equity = self._portfolio.bankroll + position_value
        await self._store.log_portfolio_snapshot(self._portfolio)

        log.info(
            "cycle_complete",
            cycle=cycle_number,
            analyzed=len(analyses),
            executed=executed,
            bankroll=round(self._portfolio.bankroll, 2),
        )
