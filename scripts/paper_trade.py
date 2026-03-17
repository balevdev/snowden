"""Run paper trading loop without OpenClaw."""
import asyncio

from snowden.agents.chief import Chief
from snowden.market import SimClient
from snowden.store import Store


async def main() -> None:
    store = Store()
    await store.connect()
    client = SimClient(store)
    chief = Chief(client, store)
    await chief.initialize()

    cycle = 0
    try:
        while True:
            cycle += 1
            await chief.run_cycle(cycle)
            await asyncio.sleep(900)
    finally:
        await client.close()
        await store.close()


if __name__ == "__main__":
    asyncio.run(main())
