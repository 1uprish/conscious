"""Finn-compatible planning contracts for the conversational hot path."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from tui_gateway.macman_conversation_planner import (
    ConversationPlanError,
    FinnConversationPlanner,
)


def _response(*calls: tuple[str, dict]):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[
            SimpleNamespace(function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))
            for name, arguments in calls
        ]))]
    )


def _envelope(source: str, content: str) -> dict:
    return {
        "source": source,
        "channel": "desktop",
        "thread_id": "chat-one",
        "message_id": "message-one",
        "content": content,
        "attachments": [],
    }


def test_user_turn_uses_exact_finn_action_tools_and_current_hermes_runtime():
    async def scenario():
        captured = {}

        async def complete(**kwargs):
            captured.update(kwargs)
            return _response(
                ("send_message", {"text": "on it"}),
                ("delegate", {"task": "open Notes"}),
                ("finish_turn", {}),
            )

        planner = FinnConversationPlanner(complete=complete)
        runtime = {
            "model": "deepseek-chat",
            "provider": "openrouter",
            "base_url": "https://example.invalid/v1",
            "api_key": "secret",
            "api_mode": "chat_completions",
        }

        actions = await planner.plan(_envelope("user", "open Notes"), main_runtime=runtime)

        assert [action["name"] for action in actions] == ["send_message", "delegate", "finish_turn"]
        assert captured["main_runtime"] is runtime
        assert captured["task"] == "conversation"
        assert {tool["function"]["name"] for tool in captured["tools"]} == {
            "send_message", "delegate", "wait", "finish_turn"
        }
        assert "open Notes" in captured["messages"][-1]["content"]

    asyncio.run(scenario())


def test_standalone_greeting_uses_the_zero_latency_conversation_path():
    async def scenario():
        def complete(**_kwargs):
            raise AssertionError("a standalone greeting must not pay for a model call")

        planner = FinnConversationPlanner(complete=complete)

        actions = await planner.plan(_envelope("user", "hey"), main_runtime={"model": "m"})

        assert actions == [
            {"name": "send_message", "arguments": {"text": "hey, what's up?"}},
            {"name": "finish_turn", "arguments": {}},
        ]

    asyncio.run(scenario())


def test_conversation_prompt_carries_the_human_hot_path_contract():
    async def scenario():
        captured = {}

        async def complete(**kwargs):
            captured.update(kwargs)
            return _response(
                ("send_message", {"text": "two secs"}),
                ("delegate", {"task": "check tomorrow's weather"}),
                ("finish_turn", {}),
            )

        planner = FinnConversationPlanner(complete=complete)
        await planner.plan(
            _envelope("user", "what's the weather tomorrow?"),
            main_runtime={"model": "m"},
        )

        system_prompt = captured["messages"][0]["content"].lower()
        assert "quietly find out" in system_prompt
        assert "two or three words" in system_prompt
        assert "worker results are evidence" in system_prompt
        assert "never mention workers" in system_prompt
        assert "never stack questions" in system_prompt
        assert "generic help" in system_prompt

    asyncio.run(scenario())


def test_worker_turn_removes_delegate_from_the_available_tool_surface():
    async def scenario():
        captured = {}

        async def complete(**kwargs):
            captured.update(kwargs)
            return _response(("send_message", {"text": "done"}), ("finish_turn", {}))

        planner = FinnConversationPlanner(complete=complete)
        await planner.plan(_envelope("worker", "Notes is open"), main_runtime={"model": "m"})

        assert {tool["function"]["name"] for tool in captured["tools"]} == {
            "send_message", "wait", "finish_turn"
        }
        assert "internal worker result" in captured["messages"][-1]["content"].lower()

    asyncio.run(scenario())


def test_current_conversation_and_follow_up_workers_are_private_planner_context():
    async def scenario():
        captured = {}

        async def complete(**kwargs):
            captured.update(kwargs)
            return _response(
                ("send_message", {"text": "got it"}),
                ("delegate", {"task": "open the project note", "worker_id": "worker-one"}),
                ("finish_turn", {}),
            )

        context = {
            "messages": [
                {"role": "user", "source": "user", "message_id": "one", "content": "open Notes"},
                {"role": "assistant", "source": "system", "message_id": "reply", "content": "on it"},
                {
                    "role": "user", "source": "worker", "message_id": "worker-one:complete",
                    "content": "Which note should I open?",
                },
            ],
            "active_workers": [],
            "follow_up_workers": [{
                "worker_id": "worker-one", "task": "open Notes", "status": "complete",
                "summary": "Which note should I open?", "expires_at": 402.0,
            }],
        }
        planner = FinnConversationPlanner(complete=complete)
        actions = await planner.plan(
            _envelope("user", "the project note"),
            main_runtime={"model": "m"},
            conversation_context=context,
        )

        prompt = captured["messages"][-1]["content"]
        assert "Which note should I open?" in prompt
        assert "worker-one" in prompt
        assert actions[1]["arguments"]["worker_id"] == "worker-one"
        delegate_schema = next(
            tool["function"]["parameters"]["properties"]
            for tool in captured["tools"] if tool["function"]["name"] == "delegate"
        )
        assert "worker_id" in delegate_schema

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (SimpleNamespace(choices=[]), "one choice"),
        (_response(), "tool action"),
        (_response(("send_message", {"text": "hi"})), "finish_turn"),
        (_response(("unknown", {}), ("finish_turn", {})), "unsupported"),
    ],
)
def test_invalid_model_output_fails_loud_so_the_gateway_can_fail_open(response, message):
    async def scenario():
        planner = FinnConversationPlanner(complete=lambda **_kwargs: response)
        with pytest.raises(ConversationPlanError, match=message):
            await planner.plan(_envelope("user", "do the thing"), main_runtime={"model": "m"})

    asyncio.run(scenario())


def test_invalid_tool_json_is_not_guessed_or_partially_executed():
    async def scenario():
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[
            SimpleNamespace(function=SimpleNamespace(name="send_message", arguments="{not-json")),
        ]))])
        planner = FinnConversationPlanner(complete=lambda **_kwargs: response)
        with pytest.raises(ConversationPlanError, match="JSON object"):
            await planner.plan(_envelope("user", "do the thing"), main_runtime={"model": "m"})

    asyncio.run(scenario())
