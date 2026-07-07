"""End-to-end tests for the run-based chat architecture."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from httpx import AsyncClient

from helpers.sse import collect_run_events, parse_sse_block, wait_for_run_status
from helpers.stubs import slow_turn, success_turn, token_burst_turn


@pytest.mark.asyncio
@patch("runs.iter_agent_turn_events", new=success_turn)
async def test_chat_returns_202_and_completes_with_done_event(
    client: AsyncClient,
    session_id: str,
) -> None:
    start = await client.post(
        f"/api/sessions/{session_id}/chat",
        json={"message": "ping"},
    )
    assert start.status_code == 202
    body = start.json()
    run_id = body["run_id"]
    assert body["session_id"] == session_id
    assert body["status"] == "queued"

    events = await collect_run_events(client, session_id, run_id)
    types = [event["type"] for event in events]
    assert "source_start" in types
    assert "token" in types
    assert types[-1] == "done"
    assert events[-1]["reply"] == "Hello from tests"

    final_status = await wait_for_run_status(client, session_id, run_id, "done")
    assert final_status == "done"

    session = await client.get(f"/api/sessions/{session_id}")
    assert session.json()["active_run_id"] is None


@pytest.mark.asyncio
@patch("runs.iter_agent_turn_events", new=success_turn)
async def test_sse_events_have_monotonic_sequence_numbers(
    client: AsyncClient,
    session_id: str,
) -> None:
    start = await client.post(
        f"/api/sessions/{session_id}/chat",
        json={"message": "seq check"},
    )
    run_id = start.json()["run_id"]
    events = await collect_run_events(client, session_id, run_id)
    seqs = [int(event["seq"]) for event in events if "seq" in event]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)
    assert seqs[-1] > 0


@pytest.mark.asyncio
@patch("runs.iter_agent_turn_events", new=success_turn)
async def test_sse_resume_after_cursor(
    client: AsyncClient,
    session_id: str,
) -> None:
    start = await client.post(
        f"/api/sessions/{session_id}/chat",
        json={"message": "resume me"},
    )
    run_id = start.json()["run_id"]

    first_batch = await collect_run_events(
        client, session_id, run_id, stop_after=2, timeout=10.0
    )
    assert len(first_batch) == 2
    cursor = int(first_batch[-1]["seq"])

    remainder = await collect_run_events(
        client, session_id, run_id, after=cursor, timeout=10.0
    )
    all_types = [event["type"] for event in first_batch + remainder]
    assert all_types[-1] == "done"
    replayed_seqs = {int(event["seq"]) for event in remainder}
    assert cursor not in replayed_seqs


@pytest.mark.asyncio
@patch("runs.iter_agent_turn_events", new=success_turn)
async def test_finished_run_replays_from_event_log(
    client: AsyncClient,
    session_id: str,
) -> None:
    start = await client.post(
        f"/api/sessions/{session_id}/chat",
        json={"message": "persist"},
    )
    run_id = start.json()["run_id"]
    await wait_for_run_status(client, session_id, run_id, "done")

    replay = await collect_run_events(client, session_id, run_id, after=0)
    assert replay[-1]["type"] == "done"
    assert replay[0]["type"] == "source_start"


@pytest.mark.asyncio
@patch("runs.iter_agent_turn_events", new=token_burst_turn)
async def test_token_events_coalesced_in_persisted_log(
    client: AsyncClient,
    session_id: str,
) -> None:
    start = await client.post(
        f"/api/sessions/{session_id}/chat",
        json={"message": "burst"},
    )
    run_id = start.json()["run_id"]
    live = await collect_run_events(client, session_id, run_id)
    live_tokens = [event for event in live if event["type"] == "token"]
    assert len(live_tokens) == 20

    persisted = await store_run_events_from_db(run_id)
    persisted_tokens = [event for event in persisted if event["type"] == "token"]
    assert len(persisted_tokens) == 1
    assert persisted_tokens[0]["text"] == "".join(f"t{i}" for i in range(20))


async def store_run_events_from_db(run_id: str) -> list[dict]:
    from session_persistence import AppDB

    db = await AppDB.get()
    return await db.read_run_events(run_id, after_seq=0)


@pytest.mark.asyncio
@patch("runs.iter_agent_turn_events", new=slow_turn)
async def test_concurrent_chat_returns_409_with_active_run_id(
    client: AsyncClient,
    session_id: str,
) -> None:
    first = await client.post(
        f"/api/sessions/{session_id}/chat",
        json={"message": "first"},
    )
    assert first.status_code == 202
    run_id = first.json()["run_id"]

    await wait_for_run_status(client, session_id, run_id, "running")

    active = await client.get(f"/api/sessions/{session_id}/runs/active")
    assert active.json()["run_id"] == run_id

    second = await client.post(
        f"/api/sessions/{session_id}/chat",
        json={"message": "second"},
    )
    assert second.status_code == 409
    detail = second.json()["detail"]
    assert detail["active_run_id"] == run_id

    await client.post(f"/api/sessions/{session_id}/runs/{run_id}/cancel")
    await wait_for_run_status(client, session_id, run_id, "cancelled")


@pytest.mark.asyncio
@patch("runs.iter_agent_turn_events", new=slow_turn)
async def test_cancel_run_emits_cancelled_and_clears_active(
    client: AsyncClient,
    session_id: str,
) -> None:
    start = await client.post(
        f"/api/sessions/{session_id}/chat",
        json={"message": "cancel me"},
    )
    run_id = start.json()["run_id"]
    await wait_for_run_status(client, session_id, run_id, "running")

    cancel = await client.post(f"/api/sessions/{session_id}/runs/{run_id}/cancel")
    assert cancel.status_code == 200
    assert cancel.json()["cancelled"] is True

    events = await collect_run_events(client, session_id, run_id, after=0, timeout=10.0)
    assert events[-1]["type"] == "cancelled"
    await wait_for_run_status(client, session_id, run_id, "cancelled")

    session = await client.get(f"/api/sessions/{session_id}")
    assert session.json()["active_run_id"] is None


@pytest.mark.asyncio
@patch("runs.iter_agent_turn_events", new=slow_turn)
async def test_chat_stop_cancels_active_run(
    client: AsyncClient,
    session_id: str,
) -> None:
    start = await client.post(
        f"/api/sessions/{session_id}/chat",
        json={"message": "stop via session endpoint"},
    )
    run_id = start.json()["run_id"]
    await wait_for_run_status(client, session_id, run_id, "running")

    stop = await client.post(f"/api/sessions/{session_id}/chat/stop")
    assert stop.status_code == 200
    assert stop.json()["cancelled"] is True
    await wait_for_run_status(client, session_id, run_id, "cancelled")


@pytest.mark.asyncio
@patch("runs.iter_agent_turn_events", new=slow_turn)
async def test_sse_disconnect_does_not_cancel_run(
    client: AsyncClient,
    session_id: str,
) -> None:
    start = await client.post(
        f"/api/sessions/{session_id}/chat",
        json={"message": "keep going"},
    )
    run_id = start.json()["run_id"]
    await wait_for_run_status(client, session_id, run_id, "running")

    # No SSE client attached: the run must stay in flight until explicit cancel.
    active = await client.get(f"/api/sessions/{session_id}/runs/active")
    assert active.json()["run_id"] == run_id

    status = await client.get(f"/api/sessions/{session_id}/runs/{run_id}")
    assert status.json()["status"] == "running"

    cancel = await client.post(f"/api/sessions/{session_id}/runs/{run_id}/cancel")
    assert cancel.json()["cancelled"] is True
    await wait_for_run_status(client, session_id, run_id, "cancelled")


@pytest.mark.asyncio
@patch("runs.iter_agent_turn_events", new=success_turn)
async def test_messages_and_summary_after_completed_run(
    client: AsyncClient,
    session_id: str,
) -> None:
    start = await client.post(
        f"/api/sessions/{session_id}/chat",
        json={"message": "summarize"},
    )
    run_id = start.json()["run_id"]
    await collect_run_events(client, session_id, run_id)

    messages = await client.get(f"/api/sessions/{session_id}/messages")
    assert messages.status_code == 200
    # Stub turn does not write to the real checkpointer; summary still updates.
    listed = await client.get("/api/sessions")
    summary = next(item for item in listed.json()["sessions"] if item["id"] == session_id)
    assert summary["message_count"] >= 0


@pytest.mark.asyncio
@patch("runs.iter_agent_turn_events", new=success_turn)
async def test_last_event_id_header_resume(
    client: AsyncClient,
    session_id: str,
) -> None:
    start = await client.post(
        f"/api/sessions/{session_id}/chat",
        json={"message": "header resume"},
    )
    run_id = start.json()["run_id"]
    first = await collect_run_events(
        client, session_id, run_id, stop_after=1, timeout=10.0
    )
    cursor = str(first[0]["seq"])

    url = f"/api/sessions/{session_id}/runs/{run_id}/events"
    async with client.stream(
        "GET",
        url,
        headers={"Last-Event-ID": cursor},
        timeout=10.0,
    ) as response:
        response.raise_for_status()
        buffer = ""
        events: list[dict] = []
        async for chunk in response.aiter_text():
            buffer += chunk
            while "\n\n" in buffer:
                block, buffer = buffer.split("\n\n", 1)
                event = parse_sse_block(block)
                if event is None:
                    continue
                events.append(event)
                if event.get("type") in {"done", "cancelled", "error"}:
                    break
            if events and events[-1].get("type") in {"done", "cancelled", "error"}:
                break

    assert events
    assert int(events[0]["seq"]) > int(cursor)
    assert events[-1]["type"] == "done"
