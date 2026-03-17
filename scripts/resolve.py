"""Backfill resolved market outcomes from Polymarket."""
import asyncio

from snowden.market import LiveClient
from snowden.store import Store


async def main() -> None:
    store = Store()
    await store.connect()
    client = LiveClient()

    # Get all unresolved predictions
    assert store._pool
    unresolved = await store._pool.fetch(
        "SELECT DISTINCT market_id FROM predictions WHERE resolved = false"
    )

    for row in unresolved:
        market_id = row["market_id"]
        try:
            detail = await client.get_market_detail(market_id)
            if detail.get("resolved"):
                outcome = 1 if detail.get("outcome") == "Yes" else 0
                await store.mark_resolved(market_id, outcome)
                print(f"Resolved {market_id}: outcome={outcome}")
        except Exception as e:
            print(f"Error resolving {market_id}: {e}")

    await client.close()
    await store.close()


if __name__ == "__main__":
    asyncio.run(main())
