"""Gymnasium parameter sweep for Kelly divisor and edge threshold."""
import asyncio

from snowden.env import SnowdenReplayEnv
from snowden.store import Store


async def main() -> None:
    store = Store()
    await store.connect()
    resolved = await store.get_resolved_predictions()

    if len(resolved) < 50:
        print("Need 50+ resolved predictions for backtesting.")
        return

    print(f"Backtesting with {len(resolved)} resolved predictions\n")

    for divisor in [2, 4, 6, 8]:
        for threshold_action in [1, 2, 3]:
            env = SnowdenReplayEnv(resolved, initial_bankroll=2000.0)
            obs, _ = env.reset()
            total_pnl = 0.0
            max_dd = 0.0

            while True:
                _, reward, done, _, info = env.step(threshold_action)
                total_pnl += reward
                max_dd = max(max_dd, info.get("drawdown", 0))
                if done:
                    break

            final = info.get("bankroll", 2000)
            ret = (final - 2000) / 2000
            print(
                f"Divisor={divisor} Action={threshold_action}: "
                f"Return={ret:.1%} MaxDD={max_dd:.1%} Final=${final:.0f}"
            )

    await store.close()


if __name__ == "__main__":
    asyncio.run(main())
