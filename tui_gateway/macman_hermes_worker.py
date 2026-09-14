"""Run delegated work in a full, isolated Hermes agent and return only its result."""

from __future__ import annotations

import contextlib
import threading
import uuid
from collections.abc import Callable
from typing import Any


def _thread(target):
    return threading.Thread(target=target, daemon=True)


def _final_text(result: object) -> str:
    if isinstance(result, dict):
        value = result.get("final_response", "")
    else:
        value = result
    return str(value or "").strip()


class HermesWorkerBridge:
    """Fire-and-return boundary between Finn actions and an unchanged Hermes turn."""

    def __init__(
        self,
        *,
        make_agent: Callable[[str], Any],
        worker_scope: Callable[[str], Any],
        build_message: Callable[[Any, str, list[dict]], Any],
        on_result: Callable[[dict], object],
        thread_factory: Callable[[Callable[[], None]], Any] = _thread,
        id_factory: Callable[[], str] = lambda: f"macman_{uuid.uuid4().hex[:12]}",
    ):
        self._make_agent = make_agent
        self._worker_scope = worker_scope
        self._build_message = build_message
        self._on_result = on_result
        self._thread_factory = thread_factory
        self._id_factory = id_factory

    @staticmethod
    def _result(request: dict, worker_id: str, *, status: str, content: str) -> dict:
        return {
            "source": "worker",
            "channel": str(request.get("channel") or "desktop"),
            "thread_id": str(request.get("thread_id") or ""),
            "message_id": f"{worker_id}:{status}",
            "content": content,
            "attachments": [],
            "worker_id": worker_id,
            "origin_message_id": str(request.get("origin_message_id") or ""),
            "status": status,
        }

    def delegate(self, request: dict) -> str:
        text = request.get("user_content")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("delegated user_content must be non-empty text")
        attachments = request.get("attachments", [])
        if not isinstance(attachments, list):
            raise ValueError("delegated attachments must be a list")
        worker_id = self._id_factory()

        def run() -> None:
            agent = None
            try:
                with self._worker_scope(worker_id):
                    agent = self._make_agent(worker_id)
                    # The conversational layer, not Hermes' raw stream, owns visible prose.
                    agent.stream_delta_callback = None
                    agent.interim_assistant_callback = None
                    message = self._build_message(agent, text, attachments)
                    result = agent.run_conversation(user_message=message, task_id=worker_id)
                    final = _final_text(result)
                    if final:
                        envelope = self._result(request, worker_id, status="complete", content=final)
                    else:
                        envelope = self._result(
                            request,
                            worker_id,
                            status="failed",
                            content="Hermes finished without a result.",
                        )
            except Exception as exc:
                envelope = self._result(
                    request,
                    worker_id,
                    status="failed",
                    content=f"Hermes could not finish that: {exc}",
                )
            finally:
                if agent is not None:
                    close = getattr(agent, "close", None)
                    if callable(close):
                        with contextlib.suppress(Exception):
                            close()
            self._on_result(envelope)

        self._thread_factory(run).start()
        return worker_id
