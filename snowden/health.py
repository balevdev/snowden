"""
snowden/health.py

Minimal TCP health endpoint on port 8080.
Returns JSON with system status for Docker healthcheck.
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from snowden.agents.chief import Chief

log = structlog.get_logger()


async def _handle_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    chief: Chief,
) -> None:
    try:
        await reader.read(4096)  # consume request
        body = json.dumps({
            "status": "ok",
            "last_cycle_ts": (
                chief.last_cycle_ts.isoformat() if chief.last_cycle_ts else None
            ),
            "cycle_number": chief.cycle_number,
            "ts": datetime.now(UTC).isoformat(),
        })
        response = (
            f"HTTP/1.1 200 OK\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"\r\n{body}"
        )
        writer.write(response.encode())
        await writer.drain()
    except Exception:
        pass
    finally:
        writer.close()


async def start_health_server(chief: Chief, port: int = 8080) -> asyncio.Server:
    """Start a minimal HTTP health server as a background task."""

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await _handle_connection(reader, writer, chief)

    server = await asyncio.start_server(handler, "0.0.0.0", port)
    log.info("health_server_started", port=port)
    return server
