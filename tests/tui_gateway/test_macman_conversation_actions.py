"""Finn hot-path action semantics at the Hermes delegation boundary."""

from __future__ import annotations

import asyncio

import pytest

from tui_gateway.macman_conversation_actions import (
    ConversationActionError,
    ConversationActionExecutor,
)


def user_turn(content: str = "open Notes") -> dict:
    return {
        "source": "user",
        "channel": "desktop",
        "thread_id": "chat",
        "message_id": "message-one",
        "content": content,
        "attachments": [{"name": "context.txt", "path": "/tmp/context.txt"}],
    }


def test_social_turn_delivers_without_delegating():
    async def scenario():
        delivered = []
        delegated = []
        executor = ConversationActionExecutor(
            deliver=lambda text: delivered.append(text),
            delegate=lambda request: delegated.append(request),
        )

        result = await executor.execute(
            user_turn("hey"),
            [
                {"name": "send_message", "arguments": {"text": "hey, what's up?"}},
                {"name": "finish_turn", "arguments": {}},
            ],
        )

        assert delivered == ["hey, what's up?"]
        assert delegated == []
        assert result == {"delivered": ["hey, what's up?"], "delegated": False, "waited": False}

    asyncio.run(scenario())


def test_work_turn_acknowledges_then_delegates_exact_user_request():
    async def scenario():
        events = []

        async def deliver(text):
            events.append(("message", text))

        async def delegate(request):
            events.append(("delegate", request))
            return "worker-one"

        turn = user_turn()
        executor = ConversationActionExecutor(deliver=deliver, delegate=delegate)
        result = await executor.execute(
            turn,
            [
                {"name": "send_message", "arguments": {"text": "on it"}},
                {
                    "name": "delegate",
                    "arguments": {"task": "Open Notes", "context": "Use the current Mac"},
                },
                {"name": "finish_turn", "arguments": {}},
            ],
        )

        assert events[0] == ("message", "on it")
        assert events[1][0] == "delegate"
        request = events[1][1]
        assert request["task"] == "Open Notes"
        assert request["context"] == "Use the current Mac"
        assert request["user_content"] == turn["content"]
        assert request["attachments"] == turn["attachments"]
        assert request["origin_message_id"] == turn["message_id"]
        assert result["worker_id"] == "worker-one"

    asyncio.run(scenario())


def test_missing_ack_gets_a_deterministic_receipt_before_delegation():
    async def scenario():
        events = []
        executor = ConversationActionExecutor(
            deliver=lambda text: events.append(("message", text)),
            delegate=lambda request: events.append(("delegate", request)),
        )

        await executor.execute(
            user_turn(),
            [
                {"name": "delegate", "arguments": {"task": "Open Notes"}},
                {"name": "finish_turn", "arguments": {}},
            ],
        )

        assert events[0] == ("message", "on it")
        assert events[1][0] == "delegate"

    asyncio.run(scenario())


def test_wait_is_silent_and_internal_results_cannot_delegate():
    async def scenario():
        delivered = []
        executor = ConversationActionExecutor(
            deliver=lambda text: delivered.append(text),
            delegate=lambda _request: pytest.fail("internal delivery must not delegate"),
        )
        internal = {**user_turn("done"), "source": "worker"}

        result = await executor.execute(
            internal,
            [
                {"name": "wait", "arguments": {}},
                {"name": "finish_turn", "arguments": {}},
            ],
        )
        assert delivered == []
        assert result["waited"] is True

        with pytest.raises(ConversationActionError, match="cannot delegate"):
            await executor.execute(
                internal,
                [
                    {"name": "delegate", "arguments": {"task": "try again"}},
                    {"name": "finish_turn", "arguments": {}},
                ],
            )

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("actions", "message"),
    [
        ([], "finish_turn"),
        ([{"name": "send_message", "arguments": {"text": "hi"}}], "finish_turn"),
        ([{"name": "unknown", "arguments": {}}], "unsupported"),
        ([{"name": "send_message", "arguments": {"text": " "}}, {"name": "finish_turn", "arguments": {}}], "non-empty"),
        ([{"name": "finish_turn", "arguments": {}}, {"name": "send_message", "arguments": {"text": "late"}}], "last action"),
    ],
)
def test_malformed_plans_fail_loud_for_the_caller_to_fail_open(actions, message):
    async def scenario():
        executor = ConversationActionExecutor(deliver=lambda _text: None, delegate=lambda _request: None)
        with pytest.raises(ConversationActionError, match=message):
            await executor.execute(user_turn(), actions)

    asyncio.run(scenario())
