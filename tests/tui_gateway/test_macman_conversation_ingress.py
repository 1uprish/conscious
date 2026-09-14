"""Behavior contracts for MacMan's Finn-style conversational ingress."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest

from tui_gateway.macman_conversation_ingress import ConversationIngress
from tui_gateway.macman_conversation_store import ConversationInboxStore


def message(
    message_id: str,
    *,
    source: str = "user",
    channel: str = "desktop",
    thread_id: str = "chat",
    content: str = "hey",
    attachments: list[dict] | None = None,
) -> dict:
    return {
        "source": source,
        "channel": channel,
        "thread_id": thread_id,
        "message_id": message_id,
        "content": content,
        "attachments": attachments or [],
    }


def test_store_deduplicates_and_persists_sliding_user_batches(tmp_path):
    path = tmp_path / "conversation.sqlite3"
    with ConversationInboxStore(path) as store:
        worker, created = store.accept("person", message("worker", source="worker"), now=100)
        assert created and worker["state"] == "accepted"

        first, created = store.accept(
            "person",
            message("one", attachments=[{"name": "photo.jpg"}]),
            now=100,
        )
        assert created and first["available_at"] == pytest.approx(100.5)
        duplicate, created = store.accept(
            "person",
            message("one", attachments=[{"name": "photo.jpg"}]),
            now=100.1,
        )
        assert not created and duplicate == first
        with pytest.raises(ValueError, match="different payload"):
            store.accept("person", message("one", content="changed"), now=100.1)

        store.accept("person", message("two"), now=100.3)
        assert store.claim("person", "early", now=100.6) == []

    with ConversationInboxStore(path) as store:
        batch = store.claim("person", "turn-one", now=100.8)
        assert [row["envelope"]["message_id"] for row in batch] == ["one", "two"]
        assert batch[0]["envelope"]["attachments"] == [{"name": "photo.jpg"}]
        assert store.claim("person", "blocked", now=101) == []
        assert store.settle("person", "turn-one", state="handled", now=101)
        internal = store.claim("person", "turn-two", now=101)
        assert [row["id"] for row in internal] == [worker["id"]]


def test_store_serializes_admission_and_caps_each_destination_batch(tmp_path):
    path = tmp_path / "conversation.sqlite3"
    with ConversationInboxStore(path):
        pass

    def admit(_index: int):
        with ConversationInboxStore(path) as store:
            return store.accept("person", message("same"), now=100)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(admit, range(8)))

    assert sum(created for _, created in results) == 1
    assert len({row["id"] for row, _ in results}) == 1

    with ConversationInboxStore(path) as store:
        for index in range(1, 6):
            store.accept("person", message(str(index)), now=100)
        store.accept("person", message("phone", channel="imessage"), now=100)
        store.accept("other", message("same"), now=100)

        batch = store.claim("person", "desktop", now=100)
        assert len(batch) == 5
        assert {row["envelope"]["channel"] for row in batch} == {"desktop"}
        assert store.claim("person", "parallel", now=100) == []
        assert store.claim("other", "other-owner", now=101)
        assert store.settle("person", "desktop", state="handled", now=101)
        phone = store.claim("person", "phone-turn", now=101)
        assert [row["envelope"]["message_id"] for row in phone] == ["phone"]


def test_ingress_prioritizes_users_and_never_runs_two_turns_at_once(tmp_path):
    async def scenario():
        clock = [100.0]
        handled: list[dict] = []
        active = 0
        peak_active = 0
        entered = asyncio.Event()
        release = asyncio.Event()

        async def handler(turn: dict) -> None:
            nonlocal active, peak_active
            active += 1
            peak_active = max(peak_active, active)
            handled.append(turn)
            if turn["message_id"] == "weather":
                entered.set()
                await release.wait()
            active -= 1

        with ConversationInboxStore(tmp_path / "conversation.sqlite3") as store:
            ingress = ConversationIngress(store, "person", handler, clock=lambda: clock[0])
            await ingress.enqueue(message("worker", source="worker"))
            await ingress.enqueue(message("hey", content="hey"))
            clock[0] += 0.3
            await ingress.enqueue(message("weather", content="weather?"))
            assert await ingress.drain_ready() == 0

            clock[0] += 0.6
            draining = asyncio.create_task(ingress.drain_ready())
            await entered.wait()
            await ingress.enqueue(message("next", content="also open notes"))
            assert await ingress.drain_ready() == 0
            release.set()
            assert await draining == 3

            assert [turn["message_id"] for turn in handled] == ["weather", "next", "worker"]
            assert handled[0]["content"] == "hey\n\nweather?"
            assert [part["message_id"] for part in handled[0]["parts"]] == ["hey", "weather"]
            assert peak_active == 1

    asyncio.run(scenario())


def test_cancelled_processing_claim_is_not_replayed_after_restart(tmp_path):
    async def scenario():
        path = tmp_path / "conversation.sqlite3"
        entered = asyncio.Event()
        calls: list[str] = []

        async def handler(turn: dict) -> None:
            calls.append(turn["message_id"])
            entered.set()
            await asyncio.Event().wait()

        with ConversationInboxStore(path) as store:
            ingress = ConversationIngress(store, "person", handler, grouping_window=0)
            await ingress.enqueue(message("uncertain"))
            draining = asyncio.create_task(ingress.drain_ready())
            await entered.wait()
            draining.cancel()
            with pytest.raises(asyncio.CancelledError):
                await draining
            assert store.list_pending("person")[0]["state"] == "processing"

        with ConversationInboxStore(path) as store:
            restarted = ConversationIngress(store, "person", handler, grouping_window=0)
            assert await restarted.drain_ready() == 0
            assert calls == ["uncertain"]

    asyncio.run(scenario())
