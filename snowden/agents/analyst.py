"""
snowden/agents/analyst.py

LLM-based probability estimation. Uses Claude Opus for deep analysis.
Prompt engineering is the core IP of this module.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

import anthropic
import structlog

from snowden.config import settings
from snowden.news import fetch_news_for_market
from snowden.types import EventAnalysis, Regime, ScanResult, Strategy

if TYPE_CHECKING:
    from snowden.calibrate import Calibrator
    from snowden.store import Store

log = structlog.get_logger()

ANALYST_SYSTEM_PROMPT = (  # noqa: E501
    "You are a professional prediction market analyst. Your job is to estimate "
    "the TRUE probability of an event occurring, independent of what the market "
    "currently prices.\n\n"
    "CRITICAL CALIBRATION RULES:\n"
    "1. When you say 70%, the event should happen ~70% of the time.\n"
    "2. Base your estimate on EVIDENCE, not narrative. Weight hard data "
    "(polls, filings, schedules) over soft signals (sentiment, vibes, momentum).\n"
    "3. For political markets: weight polling aggregates and base rates over "
    "pundit narratives. Polls are noisy but less biased than Twitter discourse.\n"
    "4. Distinguish between 'I don't know' (confidence: low, estimate near "
    "market price) and 'I know the market is wrong' (confidence: high, "
    "estimate far from market).\n"
    "5. Common biases to AVOID:\n"
    "   - Anchoring on the current market price (form estimate BEFORE looking at mid)\n"
    "   - Narrative bias (a good story != high probability)\n"
    "   - Recency bias (last week's news != permanent shift)\n"
    "   - Round number bias (don't cluster at 50%, 75%, 90%)\n"
    "6. If evidence is thin, say so. Set confidence LOW. Do not fabricate certainty.\n\n"
    "OUTPUT FORMAT: Respond with ONLY a JSON object matching this schema:\n"
    "{\n"
    '  "market_id": "string",\n'
    '  "question": "string",\n'
    '  "p_market": float,\n'
    '  "p_est_raw": float,\n'
    '  "confidence": float,\n'
    '  "regime": "consensus"|"contested"|"catalyst_pending"'
    '|"resolution_imminent"|"stale"|"news_driven",\n'
    '  "edge": float,\n'
    '  "reasoning": "string (2-3 sentences MAX)",\n'
    '  "key_factors": ["string", ...],\n'
    '  "data_quality": float,\n'
    '  "strategy_hint": "theta_harvest"|"longshot_fade"'
    '|"news_latency"|"partisan_fade"|"stale_reprice"|null\n'
    "}\n\n"
    "IMPORTANT: p_est_raw is YOUR raw estimate BEFORE any calibration correction. "
    "The system will apply Platt scaling separately. Give your honest best estimate."
)


def build_analyst_prompt(scan: ScanResult) -> str:
    """Build the user message for a single market analysis."""
    price_history_str = ""
    if scan.price_history_7d:
        price_history_str = (
            f"\nPrice history (7d daily mids): "
            f"{[round(p, 3) for p in scan.price_history_7d]}"
        )

    news_str = (
        "\n".join(f"  - {h}" for h in scan.news_headlines[:10])
        if scan.news_headlines
        else "  No recent news found."
    )

    hours_str = (
        str(scan.market.hours_to_resolve)
        if scan.market.hours_to_resolve
        else "Unknown"
    )

    return f"""Analyze this Polymarket market:

QUESTION: {scan.market.question}
DESCRIPTION: {scan.market.description[:500]}
RESOLUTION SOURCE: {scan.market.resolution_source}

MARKET DATA:
  Current midpoint: {scan.market.mid:.3f}
  Bid/Ask: {scan.market.bid:.3f} / {scan.market.ask:.3f}
  Spread: {scan.market.spread:.3f}
  24h Volume: ${scan.market.vol_24h:,.0f}
  Open Interest: ${scan.market.open_interest:,.0f}
  Hours to resolution: {hours_str}
  Category: {scan.market.category.value}{price_history_str}

MATCHED STRATEGIES: {', '.join(s.value for s in scan.matched_strategies)}

RECENT NEWS:
{news_str}

Provide your probability estimate. Form your estimate from the EVIDENCE before
considering the market price. The market price is shown for context, not as an anchor.

Market ID for your response: {scan.market.market_id}"""


async def analyze_market(
    scan: ScanResult,
    calibrator: Calibrator,
    client: anthropic.AsyncAnthropic | None = None,
    store: Store | None = None,
) -> EventAnalysis | None:
    """Run Analyst on a single market. Returns calibrated EventAnalysis."""
    if client is None:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    # Fetch fresh news
    news_items = await fetch_news_for_market(
        scan.market.question,
        scan.market.category.value,
    )
    scan.news_headlines = [item.title for item in news_items]

    prompt = build_analyst_prompt(scan)

    try:
        response = await client.messages.create(
            model=settings.analyst_model,
            max_tokens=settings.analyst_max_tokens,
            system=ANALYST_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        block = response.content[0]
        assert isinstance(block, anthropic.types.TextBlock)
        text = block.text.strip()

        # Parse JSON (strip markdown fences if present)
        clean = text.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean)

        # Apply calibration correction
        raw_est = float(data["p_est_raw"])
        calibrated = calibrator.correct(raw_est)

        return EventAnalysis(
            market_id=data["market_id"],
            question=data["question"],
            p_market=float(data["p_market"]),
            p_est=calibrated,
            p_est_raw=raw_est,
            confidence=float(data["confidence"]),
            regime=Regime(data["regime"]),
            edge=round(calibrated - float(data["p_market"]), 4),
            reasoning=data["reasoning"],
            key_factors=data.get("key_factors", []),
            data_quality=float(data.get("data_quality", 0.5)),
            strategy_hint=(
                Strategy(data["strategy_hint"]) if data.get("strategy_hint") else None
            ),
        )

    except Exception as e:
        log.error("analyst_error", market_id=scan.market.market_id, error=str(e))
        if store:
            await store.log_error("analyst", type(e).__name__, str(e))
        return None


async def analyze_batch(
    scans: list[ScanResult],
    calibrator: Calibrator,
    store: Store | None = None,
) -> list[EventAnalysis]:
    """Analyze multiple markets. Sequential to respect rate limits."""
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    results: list[EventAnalysis] = []

    for scan in scans:
        analysis = await analyze_market(scan, calibrator, client, store=store)
        if analysis is not None:
            results.append(analysis)
            log.info(
                "analyst_result",
                market_id=analysis.market_id,
                p_market=analysis.p_market,
                p_est=analysis.p_est,
                edge=analysis.edge,
                confidence=analysis.confidence,
                regime=analysis.regime.value,
            )

    return results
