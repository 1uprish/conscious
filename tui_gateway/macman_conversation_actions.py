"""Execution boundary for Finn hot-path delivery and Hermes delegation."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Sequence
from typing import Any


_SUPPORTED_ACTIONS = frozenset({"send_message", "delegate", "wait", "finish_turn"})


class ConversationActionError(ValueError):
    """A hot-path plan is unsafe or malformed and must fail open to Hermes."""


async def _resolve(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _non_empty_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConversationActionError(f"{field} must be non-empty text")
    return value.strip()


class ConversationActionExecutor:
    """Execute the small Finn action surface without exposing Hermes tools to it."""

    def __init__(
        self,
        *,
        deliver: Callable[[str], object | Awaitable[object]],
        delegate: Callable[[dict], object | Awaitable[object]],
        fallback_ack: str = "on it",
    ):
        self._deliver = deliver
        self._delegate = delegate
        self._fallback_ack = _non_empty_text(fallback_ack, "fallback_ack")

    @staticmethod
    def _validated_actions(source: str, actions: Sequence[dict]) -> list[tuple[str, dict]]:
        if not isinstance(actions, Sequence) or isinstance(actions, (str, bytes)):
            raise ConversationActionError("actions must be a sequence")
        validated: list[tuple[str, dict]] = []
        for action in actions:
            if not isinstance(action, dict):
                raise ConversationActionError("each action must be an object")
            name = action.get("name")
            if name not in _SUPPORTED_ACTIONS:
                raise ConversationActionError(f"unsupported conversation action: {name!r}")
            arguments = action.get("arguments", {})
            if not isinstance(arguments, dict):
                raise ConversationActionError(f"{name} arguments must be an object")
            if name == "send_message":
                _non_empty_text(arguments.get("text"), "send_message text")
            elif name == "delegate":
                if source != "user":
                    raise ConversationActionError(f"{source} turns cannot delegate")
                _non_empty_text(arguments.get("task"), "delegate task")
                context = arguments.get("context")
                if context is not None and not isinstance(context, str):
                    raise ConversationActionError("delegate context must be text")
                worker_id = arguments.get("worker_id")
                if worker_id is not None:
                    _non_empty_text(worker_id, "delegate worker_id")
            validated.append((name, arguments))

        finish_indexes = [index for index, (name, _args) in enumerate(validated) if name == "finish_turn"]
        if len(finish_indexes) != 1:
            raise ConversationActionError("plan must contain exactly one finish_turn action")
        if finish_indexes[0] != len(validated) - 1:
            raise ConversationActionError("finish_turn must be the last action")
        return validated

    async def execute(self, envelope: dict, actions: Sequence[dict]) -> dict:
        if not isinstance(envelope, dict):
            raise ConversationActionError("envelope must be an object")
        source = envelope.get("source")
        if source not in {"user", "worker", "trigger"}:
            raise ConversationActionError("envelope source is unsupported")
        validated = self._validated_actions(source, actions)

        delivered: list[str] = []
        delegated = False
        worker_id = None
        waited = False
        for name, arguments in validated:
            if name == "send_message":
                text = _non_empty_text(arguments.get("text"), "send_message text")
                await _resolve(self._deliver(text))
                delivered.append(text)
            elif name == "delegate":
                if not delivered:
                    await _resolve(self._deliver(self._fallback_ack))
                    delivered.append(self._fallback_ack)
                request = {
                    "task": _non_empty_text(arguments.get("task"), "delegate task"),
                    "context": arguments.get("context") or "",
                    "user_content": envelope.get("content", ""),
                    "attachments": list(envelope.get("attachments", [])),
                    "origin_message_id": envelope.get("message_id", ""),
                    "channel": envelope.get("channel", ""),
                    "thread_id": envelope.get("thread_id", ""),
                }
                if arguments.get("worker_id") is not None:
                    request["worker_id"] = _non_empty_text(
                        arguments.get("worker_id"), "delegate worker_id",
                    )
                worker_id = await _resolve(self._delegate(request))
                delegated = True
            elif name == "wait":
                waited = True

        return {
            "delivered": delivered,
            "delegated": delegated,
            "waited": waited,
            **({"worker_id": worker_id} if worker_id is not None else {}),
        }
