"""
snowden/scanner.py

5-stage market scanning funnel. Reduces 500+ markets to 10-15 opportunities.
Pure Polars operations for Stages 1-4. Single Haiku call for Stage 5.
"""
from __future__ import annotations

from typing import Literal

import anthropic
import polars as pl

from snowden.config import settings
from snowden.types import MarketCategory, MarketSnapshot, ScanResult, Strategy

# Internal scoring weights (not user-tunable)
_EDGE_SCALE_LONGSHOT = 0.5
_EDGE_EST_STALE = 0.04
_EDGE_EST_PARTISAN = 0.06
_CONFIDENCE_MOD_DEFAULT = 0.7
_TIME_DECAY_FLOOR = 0.3
_LIQUIDITY_NORM = 50_000.0
_TIME_DECAY_DAYS = 60.0


def stage_2_liquidity_gate(df: pl.DataFrame) -> pl.DataFrame:
    """Filter markets by minimum liquidity requirements."""
    return df.filter(
        (pl.col("vol_24h") >= settings.min_liquidity_usd)
        & ((pl.col("bid_depth") + pl.col("ask_depth")) >= settings.min_book_depth_usd)
        & (pl.col("spread") <= settings.max_spread)
        & (pl.col("hours_to_resolve") >= settings.min_hours_to_resolve)
        & (pl.col("hours_to_resolve") <= settings.max_days_to_resolve * 24)
    )


def stage_3_efficiency_score(df: pl.DataFrame) -> pl.DataFrame:
    """Compute efficiency score. Lower = more beatable."""
    return df.with_columns(
        (
            # Spread component: wider = less efficient
            (pl.col("spread") / settings.max_spread).clip(0, 1) * 0.25
            # Volume component: lower volume = less efficient
            + (1.0 - (pl.col("vol_24h") / 100_000).clip(0, 1)) * 0.20
            # Depth component: shallow book = less efficient
            + (1.0 - ((pl.col("bid_depth") + pl.col("ask_depth")) / 10_000).clip(0, 1)) * 0.15
            # Price extremity: prices near 0 or 1 have known biases
            + (1.0 - (2 * (pl.col("mid") - 0.5).abs())).clip(0, 1) * 0.15
            # Time component: 1-4 week resolution is sweet spot
            + pl.when(
                (pl.col("hours_to_resolve") >= 168) & (pl.col("hours_to_resolve") <= 672)
            )
            .then(0.0)
            .otherwise(0.25)
            * 0.25
        ).alias("efficiency_score")
    ).filter(pl.col("efficiency_score") <= settings.efficiency_score_cutoff)


def stage_4_strategy_match(df: pl.DataFrame) -> list[ScanResult]:
    """Classify markets into strategy buckets and score."""
    results: list[ScanResult] = []

    for row in df.iter_rows(named=True):
        matched: list[Strategy] = []
        max_edge_est = 0.0

        mid = row["mid"]
        hours = row["hours_to_resolve"] or 999

        # Theta harvest: near-certain outcomes
        if mid >= settings.theta_boundary or mid <= 1.0 - settings.theta_boundary:
            matched.append(Strategy.THETA)
            distance = min(mid, 1.0 - mid)
            max_edge_est = max(max_edge_est, distance)

        # Longshot fade: overpriced tails
        if mid <= settings.longshot_boundary or mid >= 1.0 - settings.longshot_boundary:
            matched.append(Strategy.LONGSHOT_FADE)
            max_edge_est = max(max_edge_est, min(mid, 1.0 - mid) * _EDGE_SCALE_LONGSHOT)

        # Stale reprice: unchanged price, low volume
        vol = row.get("vol_24h", 0)
        spread = row.get("spread", 0)
        if vol < settings.stale_vol_threshold and spread > settings.stale_spread_threshold:
            matched.append(Strategy.STALE_REPRICE)
            max_edge_est = max(max_edge_est, _EDGE_EST_STALE)

        # Partisan fade: political + mid range
        cat = row.get("category", "")
        is_political = cat in ("politics_us", "politics_intl")
        if is_political and settings.partisan_mid_low < mid < settings.partisan_mid_high:
            matched.append(Strategy.PARTISAN_FADE)
            max_edge_est = max(max_edge_est, _EDGE_EST_PARTISAN)

        if not matched:
            continue

        # Priority scoring
        confidence_mod = (
            1.0
            if Strategy.THETA in matched or Strategy.LONGSHOT_FADE in matched
            else _CONFIDENCE_MOD_DEFAULT
        )
        liquidity_score = min(1.0, row["vol_24h"] / _LIQUIDITY_NORM)
        days = hours / 24
        time_decay = max(_TIME_DECAY_FLOOR, 1.0 - (days / _TIME_DECAY_DAYS))
        priority = max_edge_est * confidence_mod * liquidity_score / max(time_decay, 0.1)

        cat_enum = (
            MarketCategory(cat)
            if cat in [e.value for e in MarketCategory]
            else MarketCategory.OTHER
        )

        snapshot = MarketSnapshot(
            market_id=row["market_id"],
            condition_id=row.get("condition_id", ""),
            question=row["question"],
            description=row.get("description", ""),
            category=cat_enum,
            end_date=row.get("end_date"),
            resolution_source=row.get("resolution_source", ""),
            active=True,
            yes_token_id=row["yes_token_id"],
            no_token_id=row["no_token_id"],
            mid=mid,
            bid=row.get("bid", mid),
            ask=row.get("ask", mid),
            spread=row.get("spread", 0),
            vol_24h=row["vol_24h"],
            bid_depth=row.get("bid_depth", 0),
            ask_depth=row.get("ask_depth", 0),
            open_interest=row.get("open_interest", 0),
            hours_to_resolve=hours,
            efficiency_score=row.get("efficiency_score", 0),
            opportunity_score=priority,
        )

        direction: Literal["YES", "NO", "UNCLEAR"] = "UNCLEAR"
        if mid < 0.5 and Strategy.LONGSHOT_FADE not in matched:
            direction = "YES"
        elif mid > 0.5 and Strategy.LONGSHOT_FADE in matched:
            direction = "NO"

        results.append(
            ScanResult(
                market=snapshot,
                matched_strategies=matched,
                priority_score=priority,
                suggested_direction=direction,
            )
        )

    results.sort(key=lambda r: r.priority_score, reverse=True)
    return results[:settings.scanner_result_limit]


async def stage_5_haiku_triage(
    candidates: list[ScanResult],
    anthropic_client: anthropic.AsyncAnthropic,
) -> list[ScanResult]:
    """Haiku pre-screen: is this worth deep Analyst analysis?"""
    if not candidates:
        return []

    batch_text = "\n".join(
        f"[{i}] Q: {c.market.question} | Mid: {c.market.mid:.2f} | "
        f"Strategies: {', '.join(s.value for s in c.matched_strategies)} | "
        f"Vol24h: ${c.market.vol_24h:,.0f} | Spread: {c.market.spread:.3f}"
        for i, c in enumerate(candidates)
    )

    response = await anthropic_client.messages.create(
        model=settings.triage_model,
        max_tokens=500,
        system=(
            "You are a prediction market pre-screener. For each market below, "
            "respond with ONLY the index numbers of markets worth deep analysis. "
            "Skip markets that are: obviously efficiently priced, have no clear "
            "information advantage, or are too ambiguous to estimate. "
            "Select 10-15 markets maximum. Respond as comma-separated indices only."
        ),
        messages=[{"role": "user", "content": batch_text}],
    )

    block = response.content[0]
    assert isinstance(block, anthropic.types.TextBlock)
    text = block.text.strip()
    try:
        indices = [int(x.strip()) for x in text.split(",") if x.strip().isdigit()]
    except ValueError:
        indices = list(range(min(15, len(candidates))))

    return [candidates[i] for i in indices if i < len(candidates)]
