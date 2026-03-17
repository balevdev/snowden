"""
snowden/sim.py

Paper trading coordinator. Wraps SimClient with cycle management.
Used by scripts/paper_trade.py for standalone operation (no OpenClaw).
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from snowden.config import settings
from snowden.market import SimClient
from snowden.store import Store

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine
    from typing import Any

log = structlog.get_logger()


async def run_paper_cycle(
    client: SimClient,
    store: Store,
    cycle_fn: Callable[..., Coroutine[Any, Any, None]],
    cycle_number: int,
) -> None:
    """Execute one paper trading cycle."""
    log.info("paper_cycle_start", cycle=cycle_number, mode="paper")
    try:
        await cycle_fn(client, store, cycle_number)
    except Exception as e:
        log.error("paper_cycle_error", cycle=cycle_number, error=str(e))
    log.info("paper_cycle_end", cycle=cycle_number)


async def run_paper_loop(cycle_fn: Callable[..., Coroutine[Any, Any, None]]) -> None:
    """Run continuous paper trading loop."""
    store = Store()
    await store.connect()
    client = SimClient(store)
    cycle = 0

    try:
        while True:
            cycle += 1
            await run_paper_cycle(client, store, cycle_fn, cycle)
            log.info("sleeping", seconds=settings.cycle_interval)
            await asyncio.sleep(settings.cycle_interval)
    finally:
        await client.close()
        await store.close()
