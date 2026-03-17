"""
snowden/agents/chief.py

Orchestrator agent. Runs the complete trading cycle.
Manages portfolio state. Dispatches to Analyst, Sentinel, Trader.
"""
from __future__ import annotations

import asyncio
import time
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import anthropic
import structlog

from snowden.agents.analyst import analyze_batch
from snowden.agents.sentinel import check_kill_switch, check_signal
from snowden.agents.trader import execute_signal
from snowden.alerts import send_alert
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
        # PnL tracking
        self._equity_hwm: float = settings.bankroll
        self._day_start: date = datetime.now(UTC).date()
        self._day_start_equity: float = settings.bankroll
        # Periodic task timestamps
        self._last_resolve_check: datetime = datetime.min.replace(tzinfo=UTC)
        self._last_calibration: datetime = datetime.min.replace(tzinfo=UTC)
        # Health tracking
        self.last_cycle_ts: datetime | None = None

    @property
    def cycle_number(self) -> int:
        return self._portfolio.cycle_number

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

        # Restore HWM from last snapshot
        snapshot = await self._store.get_last_snapshot()
        if snapshot:
            self._equity_hwm = max(
                snapshot.get("total_equity", settings.bankroll),
                settings.bankroll,
            )
            self._day_start_equity = self._equity_hwm

        log.info("chief_initialized", calibrator_fitted=self._calibrator.is_fitted)

    async def _refresh_midpoints(self) -> None:
        """Update current_mid and unrealized_pnl for all positions."""
        if not self._portfolio.positions:
            return
        sem = asyncio.Semaphore(5)

        async def _fetch(pos: Position) -> tuple[Position, float | None]:
            try:
                async with sem:
                    mid = await self._client.get_midpoint(pos.token_id)
                return pos, mid
            except Exception as e:
                log.warning("midpoint_refresh_failed", token_id=pos.token_id, error=str(e))
                return pos, None

        results = await asyncio.gather(*[_fetch(p) for p in self._portfolio.positions])
        for pos, mid in results:
            if mid is not None:
                pos.current_mid = mid
                pos.unrealized_pnl = pos.size_usd * (pos.current_mid / pos.avg_price - 1.0)

    def _update_pnl(self) -> None:
        """Compute daily PnL, equity, and drawdown."""
        today = datetime.now(UTC).date()
        if today != self._day_start:
            # Day rollover
            self._day_start = today
            self._day_start_equity = self._portfolio.total_equity
            self._equity_hwm = self._portfolio.total_equity
            self._portfolio.realized_pnl_total = 0.0
            self._portfolio.trade_count_today = 0
            log.info("day_rollover", new_day=str(today))

        total_equity = self._portfolio.bankroll + sum(
            p.size_usd + p.unrealized_pnl for p in self._portfolio.positions
        )
        self._portfolio.total_equity = total_equity
        self._portfolio.daily_pnl = total_equity - self._day_start_equity
        self._equity_hwm = max(self._equity_hwm, total_equity)
        self._portfolio.daily_drawdown = (
            max(0.0, (self._equity_hwm - total_equity) / self._equity_hwm)
            if self._equity_hwm > 0
            else 0.0
        )

    async def _check_exits(self) -> None:
        """Check positions for exit conditions: resolution, stop-loss, time."""
        if not self._portfolio.positions:
            return
        now = datetime.now(UTC)
        to_close: list[tuple[Position, str, float]] = []

        for pos in list(self._portfolio.positions):
            try:
                # Resolution exit
                detail = await self._client.get_market_detail(pos.market_id)
                if detail.get("resolved") or detail.get("closed"):
                    outcome_price = 1.0 if detail.get("outcome") == "Yes" else 0.0
                    if pos.direction == "NO":
                        outcome_price = 1.0 - outcome_price
                    to_close.append((pos, "resolved", outcome_price))
                    continue
            except Exception as e:
                log.warning(
                    "exit_check_market_detail_failed",
                    market_id=pos.market_id, error=str(e),
                )
                await self._store.log_error("chief", "exit_check", str(e))

            # Stop-loss
            if pos.size_usd > 0 and pos.unrealized_pnl / pos.size_usd < -settings.stop_loss_pct:
                to_close.append((pos, "stop_loss", pos.current_mid))
                continue

            # Time exit
            hold_hours = (now - pos.opened_at).total_seconds() / 3600
            if hold_hours > settings.max_position_hold_hours:
                to_close.append((pos, "time_exit", pos.current_mid))
                continue

        for pos, reason, exit_price in to_close:
            try:
                pnl = pos.size_usd * (exit_price / pos.avg_price - 1.0)
                await self._store.log_close_trade(pos, reason, exit_price)
                self._portfolio.realized_pnl_total += pnl
                self._portfolio.bankroll += pos.size_usd + pnl
                if self._portfolio.total_equity > 0:
                    self._portfolio.heat = max(
                        0.0,
                        self._portfolio.heat - pos.size_usd / self._portfolio.total_equity,
                    )
                else:
                    self._portfolio.heat = 0.0
                self._portfolio.positions.remove(pos)
                log.info(
                    "position_closed",
                    market_id=pos.market_id,
                    reason=reason,
                    pnl=round(pnl, 2),
                    exit_price=round(exit_price, 4),
                )
            except Exception as e:
                log.error("close_position_failed", market_id=pos.market_id, error=str(e))
                await self._store.log_error("chief", "close_position", str(e))

    async def _resolve_markets(self) -> None:
        """Backfill resolved outcomes for tracked markets."""
        now = datetime.now(UTC)
        if (now - self._last_resolve_check).total_seconds() < 3600:
            return
        self._last_resolve_check = now

        market_ids = await self._store.get_unresolved_market_ids()
        resolved_count = 0
        for market_id in market_ids:
            try:
                detail = await self._client.get_market_detail(market_id)
                if detail.get("resolved"):
                    outcome = 1 if detail.get("outcome") == "Yes" else 0
                    await self._store.mark_resolved(market_id, outcome)
                    resolved_count += 1
            except Exception as e:
                log.warning("resolve_failed", market_id=market_id, error=str(e))

        if resolved_count:
            log.info("markets_resolved", count=resolved_count)

    async def _maybe_recalibrate(self) -> None:
        """Re-fit calibrator every 24h."""
        now = datetime.now(UTC)
        if (now - self._last_calibration).total_seconds() < 86400:
            return
        self._last_calibration = now
        await self._calibrator.fit_from_db(self._store)
        log.info("calibrator_refit", fitted=self._calibrator.is_fitted)

    async def _scan(self) -> tuple[list[ScanResult], dict[str, int], float, dict[str, float]]:
        """Run scanning stages 1-5 with per-stage timing."""
        t0 = time.monotonic()
        stage_durations: dict[str, float] = {}

        t_s1 = time.monotonic()
        raw_df = await self._client.get_active_markets()
        stage_counts = {"stage_1": len(raw_df)}
        stage_durations["s1_ms"] = (time.monotonic() - t_s1) * 1000

        t_s2 = time.monotonic()
        filtered = stage_2_liquidity_gate(raw_df)
        stage_counts["stage_2"] = len(filtered)
        stage_durations["s2_ms"] = (time.monotonic() - t_s2) * 1000

        t_s3 = time.monotonic()
        scored = stage_3_efficiency_score(filtered)
        stage_counts["stage_3"] = len(scored)
        stage_durations["s3_ms"] = (time.monotonic() - t_s3) * 1000

        t_s4 = time.monotonic()
        candidates = stage_4_strategy_match(scored)
        stage_counts["stage_4"] = len(candidates)
        stage_durations["s4_ms"] = (time.monotonic() - t_s4) * 1000

        t_s5 = time.monotonic()
        approved = await stage_5_haiku_triage(candidates, self._anthropic)
        stage_counts["stage_5"] = len(approved)
        stage_durations["s5_ms"] = (time.monotonic() - t_s5) * 1000

        duration_ms = (time.monotonic() - t0) * 1000
        return approved, stage_counts, duration_ms, stage_durations

    async def run_cycle(self, cycle_number: int) -> None:
        """Execute one complete trading cycle."""
        cycle_t0 = time.monotonic()
        self._portfolio.cycle_number = cycle_number

        try:
            # Reload positions from DB
            positions_df = await self._store.get_active_positions()
            self._portfolio.positions = self._build_positions(positions_df)

            # Refresh midpoints and compute PnL
            await self._refresh_midpoints()
            self._update_pnl()

            # Check exits
            await self._check_exits()

            # Kill switch check
            if check_kill_switch(self._portfolio):
                log.critical(
                    "FROZEN",
                    reason="kill_switch_active",
                    drawdown=self._portfolio.daily_drawdown,
                )
                await send_alert(
                    f"KILL SWITCH ACTIVATED - drawdown {self._portfolio.daily_drawdown:.1%}"
                )
                return

            # Scan
            approved, stage_counts, scan_ms, stage_durations = await self._scan()

            # Batch-log ticks for approved markets
            tick_rows = []
            now = datetime.now(UTC)
            for scan in approved:
                tick_rows.append({
                    "ts": now,
                    "token_id": scan.market.yes_token_id,
                    "market_id": scan.market.market_id,
                    "mid": scan.market.mid,
                    "spread": scan.market.spread,
                    "vol_24h": scan.market.vol_24h,
                    "bid_depth": scan.market.bid_depth,
                    "ask_depth": scan.market.ask_depth,
                })
            if tick_rows:
                await self._store.log_ticks_batch(tick_rows)

            log.info("scan_complete", stages=stage_counts, duration_ms=round(scan_ms))

            if not approved:
                log.info("no_opportunities")
                # Still log metrics and snapshot
                await self._store.log_scan_metrics_extended(
                    stage_counts, scan_ms, stage_durations,
                    cycle_success=True,
                    cycle_duration_ms=(time.monotonic() - cycle_t0) * 1000,
                )
                await self._store.log_portfolio_snapshot(self._portfolio)
                self.last_cycle_ts = datetime.now(UTC)
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
            analyses = await analyze_batch(approved, self._calibrator, store=self._store)
            log.info("analyst_complete", count=len(analyses))

            # Build signals, risk-check, execute
            executed = 0
            for analysis in analyses:
                if analysis.confidence < settings.min_confidence:
                    continue

                # Duplicate trade protection (Step 5.1)
                if any(p.market_id == analysis.market_id for p in self._portfolio.positions):
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
            self._update_pnl()
            await self._store.log_portfolio_snapshot(self._portfolio)

            # Log extended scan metrics
            cycle_duration_ms = (time.monotonic() - cycle_t0) * 1000
            await self._store.log_scan_metrics_extended(
                stage_counts, scan_ms, stage_durations,
                cycle_success=True,
                cycle_duration_ms=cycle_duration_ms,
            )

            # Periodic tasks
            await self._resolve_markets()
            await self._maybe_recalibrate()

            self.last_cycle_ts = datetime.now(UTC)

            log.info(
                "cycle_complete",
                cycle=cycle_number,
                analyzed=len(analyses),
                executed=executed,
                bankroll=round(self._portfolio.bankroll, 2),
                daily_pnl=round(self._portfolio.daily_pnl, 2),
                daily_drawdown=round(self._portfolio.daily_drawdown, 4),
            )

        except Exception as e:
            cycle_duration_ms = (time.monotonic() - cycle_t0) * 1000
            log.error("cycle_failed", cycle=cycle_number, error=str(e))
            await self._store.log_error("chief", "cycle_failure", str(e))
            await self._store.log_scan_metrics_extended(
                {}, 0.0, cycle_success=False,
                cycle_error=str(e)[:500],
                cycle_duration_ms=cycle_duration_ms,
            )
            await send_alert(f"Cycle {cycle_number} FAILED: {e}")
            raise
