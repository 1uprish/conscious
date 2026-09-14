"""Composition contracts for Finn delivery around the Hermes runtime."""

from __future__ import annotations

import asyncio

from tui_gateway.macman_conversation_planner import ConversationPlanError
from tui_gateway.macman_conversation_runtime import MacManConversationRuntime


def _turn(source="user", content="hey"):
    return {
        "source": source,
        "channel": "desktop",
        "thread_id": "chat",
        "message_id": "one",
        "content": content,
        "attachments": [],
    }


def test_social_turn_stays_in_finn_and_never_runs_hermes():
    async def scenario():
        delivered = []
        delegated = []

        class Planner:
            async def plan(self, envelope, *, main_runtime):
                assert envelope["content"] == "hey"
                assert main_runtime == {"model": "current"}
                return [
                    {"name": "send_message", "arguments": {"text": "hey, what's up?"}},
                    {"name": "finish_turn", "arguments": {}},
                ]

        runtime = MacManConversationRuntime(
            planner=Planner(),
            current_runtime=lambda: {"model": "current"},
            deliver=delivered.append,
            delegate=delegated.append,
            fail_open=lambda _turn: None,
        )
        await runtime.handle(_turn())

        assert delivered == ["hey, what's up?"]
        assert delegated == []

    asyncio.run(scenario())


def test_explicit_work_is_acknowledged_then_delegated_to_hermes():
    async def scenario():
        events = []

        class Planner:
            async def plan(self, _envelope, *, main_runtime):
                return [
                    {"name": "send_message", "arguments": {"text": "on it"}},
                    {"name": "delegate", "arguments": {"task": "open Notes"}},
                    {"name": "finish_turn", "arguments": {}},
                ]

        runtime = MacManConversationRuntime(
            planner=Planner(),
            current_runtime=lambda: {"model": "current"},
            deliver=lambda text: events.append(("message", text)),
            delegate=lambda request: events.append(("delegate", request)) or "worker-one",
            fail_open=lambda _turn: None,
        )
        result = await runtime.handle(_turn(content="open Notes"))

        assert events[0] == ("message", "on it")
        assert events[1][0] == "delegate"
        assert events[1][1]["user_content"] == "open Notes"
        assert result["worker_id"] == "worker-one"

    asyncio.run(scenario())


def test_user_plan_failure_fails_open_to_unchanged_hermes_with_exact_envelope():
    async def scenario():
        fallbacks = []

        class Planner:
            async def plan(self, _envelope, *, main_runtime):
                raise ConversationPlanError("model returned prose")

        turn = _turn(content="open Notes exactly like this")
        runtime = MacManConversationRuntime(
            planner=Planner(),
            current_runtime=lambda: {"model": "current"},
            deliver=lambda _text: None,
            delegate=lambda _request: None,
            fail_open=fallbacks.append,
        )
        result = await runtime.handle(turn)

        assert fallbacks == [turn]
        assert result == {"fallback": True}

    asyncio.run(scenario())


def test_worker_plan_failure_surfaces_truthful_hermes_result_without_redelegating():
    async def scenario():
        delivered = []

        class Planner:
            async def plan(self, _envelope, *, main_runtime):
                raise ConversationPlanError("provider down")

        runtime = MacManConversationRuntime(
            planner=Planner(),
            current_runtime=lambda: {"model": "current"},
            deliver=delivered.append,
            delegate=lambda _request: (_ for _ in ()).throw(AssertionError("must not delegate")),
            fail_open=lambda _turn: (_ for _ in ()).throw(AssertionError("must not submit worker result")),
        )
        result = await runtime.handle(_turn(source="worker", content="Notes is open"))

        assert delivered == ["Notes is open"]
        assert result == {"fallback": True, "delivered": ["Notes is open"]}

    asyncio.run(scenario())
