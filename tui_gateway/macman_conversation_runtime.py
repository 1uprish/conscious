"""Compose Finn's conversational decisions with Hermes as the sole work runtime."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from typing import Any

from tui_gateway.macman_conversation_actions import (
    ConversationActionError,
    ConversationActionExecutor,
)
from tui_gateway.macman_conversation_planner import ConversationPlanError


logger = logging.getLogger(__name__)


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
        conversation_context: Callable[[dict], object] | None = None,
        record_turn: Callable[[dict, dict], object] | None = None,
    ):
        self._planner = planner
        self._current_runtime = current_runtime
        self._deliver = deliver
        self._delegate = delegate
        self._fail_open = fail_open
        self._conversation_context = conversation_context
        self._record_turn = record_turn

    async def handle(self, envelope: dict) -> dict:
        try:
            context = (
                await _resolve(self._conversation_context(envelope))
                if self._conversation_context is not None
                else None
            )
            actions = await self._planner.plan(
                envelope,
                main_runtime=self._current_runtime(),
                conversation_context=context,
            )
        except Exception as exc:
            logger.warning(
                "Finn conversation planning failed; falling back to Hermes "
                "source=%s message_id=%s error=%s: %s",
                envelope.get("source"),
                envelope.get("message_id"),
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            return await self._fallback(envelope)
        try:
            executor = ConversationActionExecutor(
                deliver=self._deliver,
                delegate=self._delegate,
            )
            result = await executor.execute(envelope, actions)
            await self._record(envelope, result)
            return result
        except (ConversationPlanError, ConversationActionError):
            return await self._fallback(envelope)

    async def _fallback(self, envelope: dict) -> dict:
        if envelope.get("source") == "user":
            await _resolve(self._fail_open(envelope))
            return {"fallback": True}
        text = str(envelope.get("content") or "").strip()
        if text:
            await _resolve(self._deliver(text))
            result = {"fallback": True, "delivered": [text]}
            await self._record(envelope, result)
            return result
        return {"fallback": True, "delivered": []}

    async def _record(self, envelope: dict, result: dict) -> None:
        if self._record_turn is not None:
            await _resolve(self._record_turn(envelope, result))
