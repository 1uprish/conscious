"""Compose Finn's conversational decisions with Hermes as the sole work runtime."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from tui_gateway.macman_conversation_actions import (
    ConversationActionError,
    ConversationActionExecutor,
)
from tui_gateway.macman_conversation_planner import ConversationPlanError


async def _resolve(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


class MacManConversationRuntime:
    """One turn of Finn delivery; delegation is the only path into Hermes work."""

    def __init__(
        self,
        *,
        planner,
        current_runtime: Callable[[], dict],
        deliver: Callable[[str], object],
        delegate: Callable[[dict], object],
        fail_open: Callable[[dict], object],
    ):
        self._planner = planner
        self._current_runtime = current_runtime
        self._deliver = deliver
        self._delegate = delegate
        self._fail_open = fail_open

    async def handle(self, envelope: dict) -> dict:
        try:
            actions = await self._planner.plan(
                envelope,
                main_runtime=self._current_runtime(),
            )
        except Exception:
            return await self._fallback(envelope)
        try:
            executor = ConversationActionExecutor(
                deliver=self._deliver,
                delegate=self._delegate,
            )
            return await executor.execute(envelope, actions)
        except (ConversationPlanError, ConversationActionError):
            return await self._fallback(envelope)

    async def _fallback(self, envelope: dict) -> dict:
        if envelope.get("source") == "user":
            await _resolve(self._fail_open(envelope))
            return {"fallback": True}
        text = str(envelope.get("content") or "").strip()
        if text:
            await _resolve(self._deliver(text))
            return {"fallback": True, "delivered": [text]}
        return {"fallback": True, "delivered": []}
