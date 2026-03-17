"""Print current calibration metrics."""
import asyncio

from snowden.calibrate import Calibrator
from snowden.store import Store


async def main() -> None:
    store = Store()
    await store.connect()
    cal = Calibrator()
    await cal.fit_from_db(store)

    report = await cal.generate_report(store)
    if report is None:
        print("Not enough resolved predictions for a report.")
        return

    print(f"Brier Score: {report.brier_score:.4f}")
    print(f"Predictions: {report.n_predictions}")
    print(f"Resolved: {report.n_resolved}")
    print(f"Overconfidence bias: {report.overconfidence_bias:.4f}")
    print(f"Underconfidence bias: {report.underconfidence_bias:.4f}")
    print(f"Platt scaling fitted: {report.platt_fitted}")
    print("\nReliability Buckets:")
    for bucket, data in sorted(report.reliability_buckets.items()):
        predicted = data["predicted"]
        actual = data["actual"]
        count = int(data["count"])
        print(f"  {bucket}: predicted={predicted:.3f} actual={actual:.3f} n={count}")

    await store.close()


if __name__ == "__main__":
    asyncio.run(main())
