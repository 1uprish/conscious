"""Small Finn-style planning model in front of an unchanged Hermes worker runtime."""

from __future__ import annotations

import inspect
import json
import re
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

from tui_gateway.macman_conversation_actions import (
    ConversationActionError,
    ConversationActionExecutor,
)


class ConversationPlanError(ValueError):
    """The conversational model did not produce a safe executable action plan."""


_PROMPT_ROOT = Path(__file__).resolve().parents[1] / "assets" / "macman-finn"


def _macman_brand(text: str) -> str:
    """Apply the one product compatibility change to pinned Finn prompt text."""
    return re.sub(r"\bFinn\b", "MacMan", re.sub(r"\bfinn\b", "macman", text))


@lru_cache(maxsize=1)
def _system_prompt() -> str:
    """Build Finn's upstream hot-path prompt with Hermes as its execution boundary."""
    identity = (_PROMPT_ROOT / "upstream" / "FINN.xml").read_text(encoding="utf-8").strip()
    hot_path = (_PROMPT_ROOT / "upstream" / "hot-path.xml").read_text(encoding="utf-8").strip()
    contract = (_PROMPT_ROOT / "hermes-contract.xml").read_text(encoding="utf-8").strip()
    return "\n\n".join(_macman_brand(section) for section in (identity, hot_path, contract))

_GREETING_REPLIES = {
    "hey": "hey, what's up?",
    "hi": "hey, what's up?",
    "hello": "hey, what's up?",
    "yo": "yo, what's up?",
}


def _fast_social_actions(envelope: dict) -> list[dict] | None:
    if envelope.get("source") != "user" or envelope.get("attachments"):
        return None
    content = re.sub(r"[^a-z]", "", str(envelope.get("content") or "").lower())
    base = re.sub(r"(.)\1+", r"\1", content)
    reply = _GREETING_REPLIES.get(base)
    if reply is None:
        return None
    return [
        {"name": "send_message", "arguments": {"text": reply}},
        {"name": "finish_turn", "arguments": {}},
    ]


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
        "worker_id": {
            "type": "string",
            "description": "An exact follow-up worker ID supplied in private conversation context. Omit for new work.",
        },
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
    def _turn_message(envelope: dict, conversation_context: dict | None = None) -> str:
        source = envelope.get("source")
        content = str(envelope.get("content") or "")
        label = "human message" if source == "user" else f"internal {source} result"
        sections = []
        if conversation_context:
            serialized = json.dumps(
                conversation_context,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
            # This is short-term conversation continuity, not long-term memory. Keep the
            # auxiliary prompt bounded even when a worker returns a large report.
            sections.append(f"<private_conversation_context>\n{serialized[:12000]}\n</private_conversation_context>")
        sections.append(f"<{label}>\n{content}\n</{label}>")
        return "\n\n".join(sections)

    async def plan(
        self,
        envelope: dict,
        *,
        main_runtime: dict,
        conversation_context: dict | None = None,
    ) -> list[dict]:
        source = envelope.get("source")
        if source not in {"user", "worker", "trigger"}:
            raise ConversationPlanError("unsupported conversation source")
        if fast_actions := _fast_social_actions(envelope):
            return fast_actions
        response = self._complete(
            task="conversation",
            main_runtime=main_runtime,
            messages=[
                {"role": "system", "content": _system_prompt()},
                {
                    "role": "user",
                    "content": self._turn_message(envelope, conversation_context),
                },
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
