"""Small Finn-style planning model in front of an unchanged Hermes worker runtime."""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from typing import Any

from tui_gateway.macman_conversation_actions import (
    ConversationActionError,
    ConversationActionExecutor,
)


class ConversationPlanError(ValueError):
    """The conversational model did not produce a safe executable action plan."""


_SYSTEM_PROMPT = """You are MacMan's fast conversational layer.

Act like an attentive friend while preserving the user's intent exactly. You do not execute
computer work yourself. Hermes is the execution runtime behind delegate.

Rules:
- Respond to what the user just said. Never nag about unrelated unfinished work.
- Casual conversation can use send_message followed by finish_turn without delegation.
- An explicit request needing tools must get a short natural acknowledgement, then delegate
  the exact request in the same turn, then finish_turn.
- Do not silently accept user-requested work.
- Do not rewrite, narrow, expand, or invent requirements for delegated work.
- Worker results are internal context, not user messages. Deliver their useful result naturally
  with send_message, or use wait when there is nothing worth surfacing.
- Never claim work succeeded unless the worker result says it succeeded.
- User-visible output only happens through send_message. Always end with finish_turn.
"""


def _tool(name: str, description: str, properties: dict | None = None, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties or {},
                "required": required or [],
                "additionalProperties": False,
            },
        },
    }


_SEND_MESSAGE = _tool(
    "send_message",
    "Send a short user-visible conversational message.",
    {"text": {"type": "string", "description": "The exact message to show the user."}},
    ["text"],
)
_DELEGATE = _tool(
    "delegate",
    "Delegate exact user-requested work to the full Hermes runtime after acknowledging it.",
    {
        "task": {"type": "string", "description": "A faithful executable rendering of the user's request."},
        "context": {"type": "string", "description": "Only context needed to preserve references or intent."},
    },
    ["task"],
)
_WAIT = _tool("wait", "Stay silent because no user-visible message is useful yet.")
_FINISH = _tool("finish_turn", "Finish this conversational turn after all other needed actions.")


def _value(obj: object, name: str, default=None):
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def _parse_actions(response: object) -> list[dict]:
    choices = _value(response, "choices", [])
    if not isinstance(choices, (list, tuple)) or len(choices) != 1:
        raise ConversationPlanError("conversation model must return exactly one choice")
    message = _value(choices[0], "message")
    calls = _value(message, "tool_calls", [])
    if not isinstance(calls, (list, tuple)) or not calls:
        raise ConversationPlanError("conversation model must return at least one tool action")

    actions = []
    for call in calls:
        function = _value(call, "function")
        name = _value(function, "name")
        raw_arguments = _value(function, "arguments", "{}")
        try:
            arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
        except (TypeError, ValueError) as exc:
            raise ConversationPlanError("tool arguments must be a JSON object") from exc
        if not isinstance(arguments, dict):
            raise ConversationPlanError("tool arguments must be a JSON object")
        actions.append({"name": name, "arguments": arguments})
    return actions


async def _default_complete(**kwargs):
    from agent.auxiliary_client import async_call_llm

    return await async_call_llm(**kwargs)


class FinnConversationPlanner:
    """Produce only Finn's tiny conversational action surface using the active Hermes model."""

    def __init__(self, *, complete: Callable[..., Any] = _default_complete):
        self._complete = complete

    @staticmethod
    def _tools(source: str) -> list[dict]:
        return [_SEND_MESSAGE, *([_DELEGATE] if source == "user" else []), _WAIT, _FINISH]

    @staticmethod
    def _turn_message(envelope: dict) -> str:
        source = envelope.get("source")
        content = str(envelope.get("content") or "")
        label = "human message" if source == "user" else f"internal {source} result"
        return f"<{label}>\n{content}\n</{label}>"

    async def plan(self, envelope: dict, *, main_runtime: dict) -> list[dict]:
        source = envelope.get("source")
        if source not in {"user", "worker", "trigger"}:
            raise ConversationPlanError("unsupported conversation source")
        response = self._complete(
            task="conversation",
            main_runtime=main_runtime,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": self._turn_message(envelope)},
            ],
            temperature=0.2,
            max_tokens=320,
            tools=self._tools(source),
            timeout=20.0,
        )
        if inspect.isawaitable(response):
            response = await response
        actions = _parse_actions(response)
        try:
            ConversationActionExecutor._validated_actions(source, actions)
        except ConversationActionError as exc:
            raise ConversationPlanError(str(exc)) from exc
        return actions
