"""Finn-style single-owner conversational ingress for the MacMan gateway."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from tui_gateway.macman_conversation_store import ConversationInboxStore, _required_text, _settings


logger = logging.getLogger(__name__)


class ConversationIngress:
    """Group user bursts and serialize user plus internal conversational turns."""

    def __init__(
        self,
        store: ConversationInboxStore,
        owner_id: str,
        handler: Callable[[dict], Awaitable[object]],
        *,
        grouping_window: float = 0.5,
        max_coalesce_messages: int = 5,
        clock: Callable[[], float] = time.time,
    ):
        self.store = store
        self.owner_id = _required_text(owner_id, "owner_id")
        self.grouping_window, self.max_coalesce_messages = _settings(
            grouping_window,
            max_coalesce_messages,
        )
        self.handler = handler
        self.clock = clock
        self._draining = False
        self._running = False
        self._wake = asyncio.Event()

    async def enqueue(self, envelope: dict) -> tuple[dict, bool]:
        receipt = await asyncio.to_thread(
            self.store.accept,
            self.owner_id,
            envelope,
            now=self.clock(),
            grouping_window=self.grouping_window,
            max_coalesce_messages=self.max_coalesce_messages,
        )
        self._wake.set()
        return receipt

    @staticmethod
    def _coalesce(records: list[dict]) -> dict:
        parts = [record["envelope"] for record in records]
        latest = dict(parts[-1])
        if latest["source"] == "user":
            latest["content"] = "\n\n".join(part.get("content", "") for part in parts)
            latest["attachments"] = [
                attachment
                for part in parts
                for attachment in part.get("attachments", [])
            ]
            latest["parts"] = parts
        return latest

    async def drain_ready(self) -> int:
        if self._draining:
            return 0
        self._draining = True
        handled_count = 0
        try:
            while True:
                token = uuid.uuid4().hex
                claim_task = asyncio.create_task(
                    asyncio.to_thread(
                        self.store.claim,
                        self.owner_id,
                        token,
                        now=self.clock(),
                        max_coalesce_messages=self.max_coalesce_messages,
                    )
                )
                try:
                    records = await asyncio.shield(claim_task)
                except asyncio.CancelledError:
                    await claim_task
                    raise
                if not records:
                    return handled_count

                state = "handled"
                try:
                    await self.handler(self._coalesce(records))
                except Exception:
                    state = "failed"
                    logger.exception(
                        "MacMan conversation handler failed for owner %s, claim %s",
                        self.owner_id,
                        token,
                    )
                await asyncio.to_thread(
                    self.store.settle,
                    self.owner_id,
                    token,
                    state=state,
                    now=self.clock(),
                )
                handled_count += 1
        finally:
            self._draining = False

    async def run(self) -> None:
        if self._running:
            raise RuntimeError("conversation ingress is already running")
        self._running = True
        try:
            while True:
                self._wake.clear()
                await self.drain_ready()
                pending = await asyncio.to_thread(self.store.list_pending, self.owner_id)
                accepted_users = [
                    record
                    for record in pending
                    if record["state"] == "accepted" and record["source"] == "user"
                ]
                processing = any(record["state"] == "processing" for record in pending)
                delay = 1.0
                if accepted_users and not processing:
                    delay = max(
                        0.01,
                        min(delay, accepted_users[0]["available_at"] - self.clock()),
                    )
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=delay)
                except TimeoutError:
                    pass
        finally:
            self._running = False
