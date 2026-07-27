"""SSE parsing helpers for API end-to-end tests."""

from __future__ import annotations

import json
from typing import Any

from httpx import AsyncClient

TERMINAL_TYPES = frozenset({"done", "cancelled", "error"})


def parse_sse_block(block: str) -> dict[str, Any] | None:
    """Parse one SSE frame (lines joined by newlines, without trailing blank line)."""
    if not block.strip() or block.strip().startswith(":"):
        return None
    event_type: str | None = None
    data: dict[str, Any] | None = None
    for line in block.split("\n"):
        if line.startswith("event:"):
            event_type = line[6:].strip()
        elif line.startswith("data:"):
            data = json.loads(line[5:].strip())
        elif line.startswith("id:") and data is not None:
            data.setdefault("seq", int(line[3:].strip()))
    if data is None:
        return None
    if event_type and "type" not in data:
        data["type"] = event_type
    return data


async def collect_run_events(
    client: AsyncClient,
    session_id: str,
    run_id: str,
    *,
    after: int | None = None,
    timeout: float = 15.0,
    stop_after: int | None = None,
) -> list[dict[str, Any]]:
    """Read SSE events until a terminal frame or ``stop_after`` events."""
    url = f"/api/sessions/{session_id}/runs/{run_id}/events"
    params: dict[str, Any] = {}
    if after is not None:
        params["after"] = after

    events: list[dict[str, Any]] = []
    buffer = ""
    async with client.stream("GET", url, params=params, timeout=timeout) as response:
        response.raise_for_status()
        async for chunk in response.aiter_text():
            buffer += chunk
            while "\n\n" in buffer:
                block, buffer = buffer.split("\n\n", 1)
                event = parse_sse_block(block)
                if event is None:
                    continue
                events.append(event)
                if stop_after is not None and len(events) >= stop_after:
                    return events
                if event.get("type") in TERMINAL_TYPES:
                    return events
    return events


async def wait_for_run_status(
    client: AsyncClient,
    session_id: str,
    run_id: str,
    *statuses: str,
    timeout: float = 15.0,
    poll_interval: float = 0.05,
) -> str:
    """Poll run status until it matches one of ``statuses``."""
    import asyncio
    import time

    deadline = time.monotonic() + timeout
    url = f"/api/sessions/{session_id}/runs/{run_id}"
    while time.monotonic() < deadline:
        response = await client.get(url)
        response.raise_for_status()
        status = response.json()["status"]
        if status in statuses:
            return status
        await asyncio.sleep(poll_interval)
    raise TimeoutError(f"Run {run_id} did not reach {statuses!r} within {timeout}s")
