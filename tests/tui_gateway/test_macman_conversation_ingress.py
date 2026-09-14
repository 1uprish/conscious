"""Behavior contracts for MacMan's Finn-style conversational ingress."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import sqlite3

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


def test_store_uses_hermes_sqlite_safety_verdict(tmp_path):
    from hermes_state_wal import is_sqlite_wal_reset_vulnerable

    path = tmp_path / "conversation.sqlite3"
    with ConversationInboxStore(path):
        pass
    with sqlite3.connect(path) as connection:
        mode = connection.execute("PRAGMA journal_mode").fetchone()[0]

    assert mode == ("delete" if is_sqlite_wal_reset_vulnerable() else "wal")


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
        overflow = store.claim("person", "desktop-overflow", now=101)
        assert [row["envelope"]["message_id"] for row in overflow] == ["5"]
        assert store.settle("person", "desktop-overflow", state="handled", now=101)
        phone = store.claim("person", "phone-turn", now=101)
        assert [row["envelope"]["message_id"] for row in phone] == ["phone"]


def test_store_never_coalesces_across_an_interleaved_destination(tmp_path):
    with ConversationInboxStore(tmp_path / "conversation.sqlite3") as store:
        store.accept("person", message("desktop-one"), now=100, grouping_window=0)
        store.accept(
            "person",
            message("phone", channel="imessage"),
            now=100,
            grouping_window=0,
        )
        store.accept("person", message("desktop-two"), now=100, grouping_window=0)

        first = store.claim("person", "first", now=100)
        assert [row["envelope"]["message_id"] for row in first] == ["desktop-one"]
        assert store.settle("person", "first", state="handled", now=100)

        second = store.claim("person", "second", now=100)
        assert [row["envelope"]["message_id"] for row in second] == ["phone"]


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


def test_store_persists_bounded_conversation_context_separately_from_hermes_history(tmp_path):
    path = tmp_path / "conversation.sqlite3"
    with ConversationInboxStore(path) as store:
        store.record_turn(
            "person", role="user", source="user", message_id="one", content="open Notes", now=100,
        )
        store.record_turn(
            "person", role="assistant", source="system", message_id="reply-one", content="on it", now=101,
        )
        store.record_turn(
            "person", role="user", source="worker", message_id="worker-one:complete",
            content="Which note should I open?", now=102,
        )
        # A transport retry must not duplicate the logical turn.
        store.record_turn(
            "person", role="user", source="worker", message_id="worker-one:complete",
            content="Which note should I open?", now=103,
        )

    with ConversationInboxStore(path) as store:
        context = store.conversation_context("person", limit=2, now=104)

    assert context["messages"] == [
        {
            "role": "assistant", "source": "system", "message_id": "reply-one",
            "content": "on it", "created_at": 101.0,
        },
        {
            "role": "user", "source": "worker", "message_id": "worker-one:complete",
            "content": "Which note should I open?", "created_at": 102.0,
        },
    ]
    assert context["active_workers"] == []
    assert context["follow_up_workers"] == []


def test_store_exposes_only_owned_completed_workers_during_the_follow_up_window(tmp_path):
    with ConversationInboxStore(tmp_path / "conversation.sqlite3") as store:
        store.start_worker(
            "person", "worker-one", task="open Notes", origin_message_id="one", now=100,
        )
        assert store.conversation_context("person", now=101)["active_workers"] == [{
            "worker_id": "worker-one", "task": "open Notes", "status": "running",
        }]

        store.finish_worker(
            "person", "worker-one", status="complete", summary="Which note?", now=102,
            follow_up_seconds=300,
            model_messages=[
                {"role": "user", "content": "open Notes"},
                {"role": "assistant", "content": "Which note?"},
            ],
        )
        follow_up = store.conversation_context("person", now=103)["follow_up_workers"]
        assert follow_up == [{
            "worker_id": "worker-one", "task": "open Notes", "status": "complete",
            "summary": "Which note?", "expires_at": 402.0,
        }]
        assert store.claim_follow_up("other", "worker-one", now=103) is False
        assert store.claim_follow_up("person", "worker-one", now=403) is False
        assert store.claim_follow_up("person", "worker-one", now=104) is True
        assert store.get_worker_history("person", "worker-one") == [
            {"role": "user", "content": "open Notes"},
            {"role": "assistant", "content": "Which note?"},
        ]
        assert store.conversation_context("person", now=105)["active_workers"] == [{
            "worker_id": "worker-one", "task": "open Notes", "status": "running",
        }]
