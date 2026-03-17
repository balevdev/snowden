"""
snowden/agents/trader.py

Order execution agent. Receives TradeSignal, checks book depth,
places limit order with slippage guard. Pure execution, no analysis.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from snowden.config import settings
from snowden.types import OrderResult, TradeSignal

if TYPE_CHECKING:
    from snowden.market import LiveClient, SimClient
    from snowden.store import Store

log = structlog.get_logger()


async def execute_signal(
    signal: TradeSignal,
    client: LiveClient | SimClient,
    store: Store,
) -> OrderResult:
    """Execute a trade signal. Check book depth first."""
    # Pre-execution checks
    try:
        book = await client.get_book(signal.token_id)
        asks = book.get("asks", [])
        bids = book.get("bids", [])
        best_ask = float(asks[0].get("price", 1.0)) if asks else 1.0
        best_bid = float(bids[0].get("price", 0.0)) if bids else 0.0

        # Slippage guard: don't buy if book has moved > 3% against us
        if signal.direction == "YES" and best_ask > signal.p_market * settings.slippage_multiplier:
            log.warning(
                "slippage_reject", signal=signal.market_id, best_ask=best_ask
            )
            return OrderResult(status="CANCELLED", ts=datetime.now(UTC))

        if signal.direction == "NO":
            no_ask = 1.0 - best_bid
            if no_ask > (1.0 - signal.p_market) * settings.slippage_multiplier:
                log.warning("slippage_reject_no", signal=signal.market_id)
                return OrderResult(
                    status="CANCELLED", ts=datetime.now(UTC)
                )

    except Exception as e:
        log.error("book_check_failed", error=str(e))
        # Proceed with signal's limit price if book check fails

    # Execute
    result = await client.execute(signal)

    # Log
    await store.log_trade(signal, result, paper=result.status == "PAPER")
    log.info(
        "trade_executed",
        market_id=signal.market_id,
        direction=signal.direction,
        size=signal.size_usd,
        status=result.status,
        fill_price=result.fill_price,
    )

    return result
