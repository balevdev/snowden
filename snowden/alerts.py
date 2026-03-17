"""
snowden/alerts.py

Discord webhook alerting for critical system events.
"""
from __future__ import annotations

import httpx
import structlog

from snowden.config import settings

log = structlog.get_logger()


async def send_alert(message: str) -> None:
    """Send a Discord webhook alert. Fails silently."""
    if not settings.discord_webhook_url:
        log.debug("alert_skipped_no_webhook", message=message)
        return

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                settings.discord_webhook_url,
                json={"content": f"**[Snowden]** {message}"},
            )
    except Exception as e:
        log.warning("alert_send_failed", error=str(e))
