"""
snowden/news.py

News and data enrichment for market analysis.
RSS feeds via feedparser, additional free APIs via httpx.
Returns structured context for the Analyst prompt.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import feedparser


@dataclass
class NewsItem:
    title: str
    source: str
    published: datetime | None
    url: str
    summary: str


# RSS feeds organized by category for targeted enrichment
RSS_FEEDS: dict[str, list[str]] = {
    "general": [
        "https://feeds.bbci.co.uk/news/rss.xml",
        "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
        "https://feeds.reuters.com/reuters/topNews",
        "https://apnews.com/apf-topnews/feed",
    ],
    "politics_us": [
        "https://feeds.reuters.com/Reuters/PoliticsNews",
        "https://rss.nytimes.com/services/xml/rss/nyt/Politics.xml",
        "https://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml",
        "https://fivethirtyeight.com/politics/feed/",
    ],
    "crypto": [
        "https://cointelegraph.com/rss",
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
    ],
    "finance": [
        "https://feeds.reuters.com/reuters/businessNews",
        "https://feeds.bloomberg.com/markets/news.rss",
    ],
    "science": [
        "https://rss.nytimes.com/services/xml/rss/nyt/Science.xml",
        "https://www.newscientist.com/feed/home/",
    ],
    "legal": [
        "https://www.scotusblog.com/feed/",
        "https://feeds.reuters.com/reuters/domesticNews",
    ],
    "sports": [
        "https://www.espn.com/espn/rss/news",
    ],
}


async def fetch_news_for_market(
    question: str,
    category: str,
    max_items: int = 15,
    max_age_hours: int = 48,
) -> list[NewsItem]:
    """
    Fetch relevant news for a market question.
    Combines category-specific feeds with general news.
    Returns most recent items first.
    """
    feed_urls = RSS_FEEDS.get(category, []) + RSS_FEEDS["general"]
    items: list[NewsItem] = []
    cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)

    for url in feed_urls:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:20]:
                published = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    t = entry.published_parsed
                    published = datetime(
                        t[0], t[1], t[2], t[3], t[4], t[5], tzinfo=UTC,
                    )
                    if published < cutoff:
                        continue

                items.append(
                    NewsItem(
                        title=entry.get("title", ""),
                        source=feed.feed.get("title", url),
                        published=published,
                        url=entry.get("link", ""),
                        summary=entry.get("summary", "")[:200],
                    )
                )
        except Exception:
            continue  # Feed failures are non-fatal

    # Sort by recency, deduplicate by title similarity
    items.sort(key=lambda x: x.published or cutoff, reverse=True)
    seen_titles: set[str] = set()
    unique: list[NewsItem] = []
    for item in items:
        key = item.title.lower()[:50]
        if key not in seen_titles:
            seen_titles.add(key)
            unique.append(item)
        if len(unique) >= max_items:
            break

    return unique


def format_news_for_prompt(items: list[NewsItem]) -> str:
    """Format news items for inclusion in Analyst prompt."""
    if not items:
        return "No recent news found."
    lines: list[str] = []
    for item in items:
        date_str = (
            item.published.strftime("%Y-%m-%d %H:%M UTC") if item.published else "Unknown date"
        )
        lines.append(f"- [{date_str}] {item.title} ({item.source})")
    return "\n".join(lines)
