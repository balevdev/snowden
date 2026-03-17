"""
snowden/market.py

Polymarket API client. Protocol-based for swappable Live/Sim backends.
Uses httpx for async HTTP, Polars for DataFrame returns.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx
import polars as pl

from snowden.config import settings
from snowden.types import OrderResult, TradeSignal

if TYPE_CHECKING:
    from snowden.store import Store

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "politics_us": ["president", "election", "congress", "senate", "trump", "biden",
                     "governor", "democrat", "republican", "vote"],
    "crypto": ["bitcoin", "ethereum", "crypto", "btc", "eth", "solana"],
    "finance": ["fed", "interest rate", "gdp", "inflation", "stock", "s&p"],
    "sports": ["nfl", "nba", "mlb", "soccer", "championship", "super bowl"],
    "legal": ["court", "lawsuit", "ruling", "supreme court", "trial", "indictment"],
    "politics_intl": ["prime minister", "parliament", "eu ", "nato", "war", "un "],
}


def classify_category(question: str, title: str = "") -> str:
    """Simple keyword-based category classification."""
    text = (question + " " + title).lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(w in text for w in keywords):
            return category
    return "other"


class LiveClient:
    """Real Polymarket API client."""

    def __init__(self) -> None:
        self._gamma = httpx.AsyncClient(
            base_url=settings.poly_gamma_host,
            timeout=15.0,
            headers={"Accept": "application/json"},
        )
        self._clob = httpx.AsyncClient(
            base_url=settings.poly_clob_host,
            timeout=15.0,
        )
        self._data = httpx.AsyncClient(
            base_url=settings.poly_data_host,
            timeout=15.0,
        )

    async def get_active_markets(self) -> pl.DataFrame:
        """
        Fetch all active markets via Gamma API with pagination.
        Returns a Polars DataFrame with columns matching MarketSnapshot fields.
        """
        all_events: list[dict[str, Any]] = []
        offset = 0
        limit = 100

        while True:
            r = await self._gamma.get(
                "/events",
                params={"closed": "false", "limit": limit, "offset": offset},
            )
            r.raise_for_status()
            batch = r.json()
            if not batch:
                break
            all_events.extend(batch)
            if len(batch) < limit:
                break
            offset += limit

        # Flatten events -> individual markets
        rows: list[dict[str, Any]] = []
        for event in all_events:
            for market in event.get("markets", [event]):
                try:
                    raw_tokens = market.get("clobTokenIds", "")
                    if isinstance(raw_tokens, str):
                        tokens = raw_tokens.split(",")
                    else:
                        tokens = raw_tokens or ["", ""]

                    yes_token = tokens[0] if tokens else ""
                    no_token = tokens[1] if len(tokens) > 1 else ""

                    end_str = market.get("endDate") or market.get("end_date_iso")
                    end_dt = (
                        datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                        if end_str
                        else None
                    )
                    hours = (
                        (end_dt - datetime.now(UTC)).total_seconds() / 3600
                        if end_dt
                        else None
                    )

                    outcome_prices = market.get("outcomePrices", "0.5,0.5")
                    if isinstance(outcome_prices, str):
                        mid = float(outcome_prices.split(",")[0])
                    else:
                        mid = 0.5

                    rows.append(
                        {
                            "market_id": market.get(
                                "conditionId", market.get("id", "")
                            ),
                            "condition_id": market.get("conditionId", ""),
                            "question": market.get("question", ""),
                            "description": market.get("description", ""),
                            "category": classify_category(
                                market.get("question", ""), event.get("title", "")
                            ),
                            "end_date": end_dt,
                            "resolution_source": market.get("resolutionSource", ""),
                            "yes_token_id": yes_token,
                            "no_token_id": no_token,
                            "mid": mid,
                            "bid": mid - 0.01,
                            "ask": mid + 0.01,
                            "spread": 0.02,
                            "vol_24h": float(market.get("volume24hr", 0) or 0),
                            "bid_depth": 0.0,
                            "ask_depth": 0.0,
                            "open_interest": float(
                                market.get("openInterest", 0) or 0
                            ),
                            "hours_to_resolve": hours,
                        }
                    )
                except (ValueError, IndexError, KeyError):
                    continue

        return pl.DataFrame(rows)

    async def get_book(self, token_id: str) -> dict[str, Any]:
        """Fetch order book for a token."""
        r = await self._clob.get("/book", params={"token_id": token_id})
        r.raise_for_status()
        result: dict[str, Any] = r.json()
        return result

    async def get_midpoint(self, token_id: str) -> float:
        """Fetch current midpoint for a token."""
        r = await self._clob.get("/midpoint", params={"token_id": token_id})
        r.raise_for_status()
        return float(r.json().get("mid", 0))

    async def get_price_history(self, token_id: str, days: int = 14) -> pl.DataFrame:
        """Fetch price history from CLOB timeseries."""
        end = int(datetime.now(UTC).timestamp())
        start = int((datetime.now(UTC) - timedelta(days=days)).timestamp())
        r = await self._clob.get(
            "/prices-history",
            params={"market": token_id, "startTs": start, "endTs": end, "fidelity": 60},
        )
        r.raise_for_status()
        data = r.json()
        if not data or "history" not in data:
            return pl.DataFrame({"ts": [], "price": []})
        return pl.DataFrame(data["history"])

    async def get_market_detail(self, market_id: str) -> dict[str, Any]:
        """Fetch detailed market info from Gamma."""
        r = await self._gamma.get(f"/markets/{market_id}")
        r.raise_for_status()
        result: dict[str, Any] = r.json()
        return result

    async def execute(self, signal: TradeSignal) -> OrderResult:
        """Place a real order via py-clob-client."""
        from py_clob_client.client import ClobClient
        from py_clob_client.order_builder.constants import BUY

        client = ClobClient(
            settings.poly_clob_host,
            key=settings.poly_api_key,
            chain_id=137,
            funder=settings.poly_funder,
            private_key=settings.poly_private_key,
            creds={
                "apiKey": settings.poly_api_key,
                "secret": settings.poly_api_secret,
                "passphrase": settings.poly_api_passphrase,
            },
        )

        limit = signal.limit_price or signal.p_market
        order_args = {
            "token_id": signal.token_id,
            "price": round(limit, 2),
            "size": round(signal.size_usd / limit, 2),
            "side": BUY,
        }

        try:
            signed = client.create_and_sign_order(order_args)
            resp = client.post_order(signed)
            return OrderResult(
                status="FILLED" if resp.get("success") else "CANCELLED",
                order_id=resp.get("orderID"),
                fill_price=limit,
                fill_size=signal.size_usd,
                slippage=0.0,
                ts=datetime.now(UTC),
            )
        except Exception:
            return OrderResult(
                status="REJECTED",
                ts=datetime.now(UTC),
            )

    async def close(self) -> None:
        await self._gamma.aclose()
        await self._clob.aclose()
        await self._data.aclose()


class SimClient:
    """Paper trading client. Reads are real, writes are simulated."""

    def __init__(self, store: Store) -> None:
        self._store = store
        self._live = LiveClient()

    async def get_active_markets(self) -> pl.DataFrame:
        return await self._live.get_active_markets()

    async def get_book(self, token_id: str) -> dict[str, Any]:
        return await self._live.get_book(token_id)

    async def get_midpoint(self, token_id: str) -> float:
        return await self._live.get_midpoint(token_id)

    async def get_price_history(self, token_id: str, days: int = 14) -> pl.DataFrame:
        return await self._live.get_price_history(token_id, days)

    async def get_market_detail(self, market_id: str) -> dict[str, Any]:
        return await self._live.get_market_detail(market_id)

    async def execute(self, signal: TradeSignal) -> OrderResult:
        return OrderResult(
            status="PAPER",
            fill_price=signal.p_market,
            fill_size=signal.size_usd,
            slippage=0.0,
            ts=datetime.now(UTC),
        )

    async def close(self) -> None:
        await self._live.close()
