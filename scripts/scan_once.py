"""Run scanner once, print opportunities. Good for debugging."""
import asyncio

import anthropic

from snowden.config import settings
from snowden.market import LiveClient
from snowden.scanner import (
    stage_2_liquidity_gate,
    stage_3_efficiency_score,
    stage_4_strategy_match,
    stage_5_haiku_triage,
)


async def main() -> None:
    client = LiveClient()
    raw = await client.get_active_markets()
    print(f"Stage 1: {len(raw)} active markets")

    filtered = stage_2_liquidity_gate(raw)
    print(f"Stage 2: {len(filtered)} pass liquidity gate")

    scored = stage_3_efficiency_score(filtered)
    print(f"Stage 3: {len(scored)} pass efficiency filter")

    candidates = stage_4_strategy_match(scored)
    print(f"Stage 4: {len(candidates)} strategy matches")

    for c in candidates[:10]:
        strategies = ", ".join(s.value for s in c.matched_strategies)
        print(
            f"  [{c.priority_score:.3f}] {c.market.question[:60]} "
            f"| mid={c.market.mid:.2f} | {strategies}"
        )

    # Optional: run Haiku triage
    ac = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    approved = await stage_5_haiku_triage(candidates, ac)
    print(f"\nStage 5: {len(approved)} approved by Haiku")
    for a in approved:
        print(f"  {a.market.question[:70]} | mid={a.market.mid:.2f}")

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
