"""Tool-choice forwarding for callers that require an action-bearing response."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from agent.auxiliary_client import async_call_llm


def test_async_auxiliary_call_forwards_required_tool_choice_to_provider():
    async def scenario():
        client = MagicMock()
        client.base_url = "https://api.example.invalid/v1"
        response = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=response)

        with patch(
            "agent.auxiliary_client._get_cached_client",
            return_value=(client, "conversation-model"),
        ), patch(
            "agent.auxiliary_client._resolve_task_provider_model",
            return_value=("custom", "conversation-model", None, None, None),
        ):
            result = await async_call_llm(
                task="conversation",
                messages=[{"role": "user", "content": "hello"}],
                tools=[{
                    "type": "function",
                    "function": {
                        "name": "send_message",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }],
                tool_choice="required",
            )

        assert result is response
        assert client.chat.completions.create.call_args.kwargs["tool_choice"] == "required"

    asyncio.run(scenario())
