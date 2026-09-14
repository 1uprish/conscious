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
            await planner.plan(_envelope("user", "hey"), main_runtime={"model": "m"})

    asyncio.run(scenario())


def test_invalid_tool_json_is_not_guessed_or_partially_executed():
    async def scenario():
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[
            SimpleNamespace(function=SimpleNamespace(name="send_message", arguments="{not-json")),
        ]))])
        planner = FinnConversationPlanner(complete=lambda **_kwargs: response)
        with pytest.raises(ConversationPlanError, match="JSON object"):
            await planner.plan(_envelope("user", "hey"), main_runtime={"model": "m"})

    asyncio.run(scenario())
