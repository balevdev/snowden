"""Run paper trading loop without OpenClaw."""
import asyncio
import signal

import structlog

from snowden.agents.chief import Chief
from snowden.alerts import send_alert
from snowden.config import settings
from snowden.health import start_health_server
from snowden.market import DryRunClient, LiveClient, SimClient
from snowden.store import Store

log = structlog.get_logger()


async def main() -> None:
    store = Store()
    await store.connect()

    # Client selection based on mode
    if settings.mode == "live":
        client: LiveClient | SimClient | DryRunClient = LiveClient()
    elif settings.mode == "dry_run":
        client = DryRunClient()
    else:
        client = SimClient(store)

    chief = Chief(client, store)
    await chief.initialize()

    # Health server
    health_server = await start_health_server(chief)

    # Graceful shutdown
    shutdown_event = asyncio.Event()

    def _shutdown_handler() -> None:
        log.info("shutdown_signal_received")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _shutdown_handler)

    await send_alert("Snowden started")

    cycle = 0
    try:
        while not shutdown_event.is_set():
            cycle += 1
            try:
                await chief.run_cycle(cycle)
            except Exception:
                log.exception("cycle_failed", cycle=cycle)
            try:
                await asyncio.wait_for(
                    shutdown_event.wait(), timeout=settings.cycle_interval
                )
            except asyncio.TimeoutError:
                pass
    finally:
        log.info("shutting_down", cycles_completed=cycle)
        await send_alert(f"Snowden stopped after {cycle} cycles")
        health_server.close()
        await health_server.wait_closed()
        await client.close()
        await store.close()


if __name__ == "__main__":
    asyncio.run(main())
