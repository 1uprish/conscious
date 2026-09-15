"""Composition contracts for Finn delivery around the Hermes runtime."""

from __future__ import annotations

import asyncio
import logging

from tui_gateway.macman_conversation_planner import ConversationPlanError
from tui_gateway.macman_conversation_planner import FinnConversationPlanner
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
            async def plan(self, envelope, *, main_runtime, conversation_context=None):
                assert envelope["content"] == "hey"
                assert callable(main_runtime)
                assert conversation_context is None
                return [
                    {"name": "send_message", "arguments": {"text": "hey, what's up?"}},
                    {"name": "finish_turn", "arguments": {}},
                ]

        runtime = MacManConversationRuntime(
            planner=Planner(),
            current_runtime=lambda: (_ for _ in ()).throw(
                AssertionError("social turn must not wait for Hermes")
            ),
            deliver=delivered.append,
            delegate=delegated.append,
            fail_open=lambda _turn: None,
        )
        await runtime.handle(_turn())

        assert delivered == ["hey, what's up?"]
        assert delegated == []

    asyncio.run(scenario())


def test_zero_latency_identity_does_not_wait_for_the_hermes_agent_build():
    async def scenario():
        delivered = []

        def hermes_not_ready():
            raise RuntimeError("Hermes agent is not ready")

        runtime = MacManConversationRuntime(
            planner=FinnConversationPlanner(
                complete=lambda **_kwargs: (_ for _ in ()).throw(
                    AssertionError("identity must not call the model")
                ),
            ),
            current_runtime=hermes_not_ready,
            deliver=delivered.append,
            delegate=lambda _request: None,
            fail_open=lambda _turn: (_ for _ in ()).throw(
                AssertionError("identity must not fail open to Hermes")
            ),
        )

        result = await runtime.handle(_turn(content="What do I call you?"))

        assert delivered == ["macman"]
        assert result == {
            "delivered": ["macman"],
            "delegated": False,
            "waited": False,
        }

    asyncio.run(scenario())


def test_explicit_work_is_acknowledged_then_delegated_to_hermes():
    async def scenario():
        events = []

        class Planner:
            async def plan(self, _envelope, *, main_runtime, conversation_context=None):
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
            async def plan(self, _envelope, *, main_runtime, conversation_context=None):
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


def test_planner_failure_is_logged_before_fail_open(caplog):
    async def scenario():
        class Planner:
            async def plan(self, _envelope, *, main_runtime, conversation_context=None):
                raise RuntimeError("provider rejected parallel tool calls")

        runtime = MacManConversationRuntime(
            planner=Planner(),
            current_runtime=lambda: {"model": "current"},
            deliver=lambda _text: None,
            delegate=lambda _request: None,
            fail_open=lambda _turn: None,
        )

        with caplog.at_level(logging.WARNING):
            result = await runtime.handle(_turn(content="open Notes"))

        assert result == {"fallback": True}
        assert "Finn conversation planning failed" in caplog.text
        assert "provider rejected parallel tool calls" in caplog.text
        assert "message_id=one" in caplog.text

    asyncio.run(scenario())


def test_worker_plan_failure_surfaces_truthful_hermes_result_without_redelegating():
    async def scenario():
        delivered = []

        class Planner:
            async def plan(self, _envelope, *, main_runtime, conversation_context=None):
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


def test_runtime_supplies_private_context_and_records_only_the_completed_hot_path_turn():
    async def scenario():
        recorded = []
        context = {"messages": [{"content": "Which note?"}], "follow_up_workers": []}

        class Planner:
            async def plan(self, envelope, *, main_runtime, conversation_context=None):
                assert envelope["content"] == "the project note"
                assert conversation_context is context
                return [
                    {"name": "send_message", "arguments": {"text": "got it"}},
                    {"name": "finish_turn", "arguments": {}},
                ]

        turn = _turn(content="the project note")
        runtime = MacManConversationRuntime(
            planner=Planner(),
            current_runtime=lambda: {"model": "current"},
            deliver=lambda _text: None,
            delegate=lambda _request: None,
            fail_open=lambda _turn: None,
            conversation_context=lambda _envelope: context,
            record_turn=lambda envelope, result: recorded.append((envelope, result)),
        )

        result = await runtime.handle(turn)

        assert recorded == [(turn, result)]
        assert result["delivered"] == ["got it"]

    asyncio.run(scenario())
