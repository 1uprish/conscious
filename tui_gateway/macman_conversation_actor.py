"""Live gateway actor for Finn-style conversation over full Hermes workers."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from pathlib import Path

from tui_gateway.macman_conversation_actions import ConversationActionError
from tui_gateway.macman_conversation_ingress import ConversationIngress
from tui_gateway.macman_conversation_planner import FinnConversationPlanner
from tui_gateway.macman_conversation_runtime import MacManConversationRuntime
from tui_gateway.macman_conversation_store import ConversationInboxStore
from tui_gateway.macman_hermes_worker import HermesWorkerBridge


logger = logging.getLogger(__name__)


class MacManConversationActor:
    """One durable, serialized conversational owner attached to a live desktop session."""

    def __init__(self, server, sid: str, session: dict, *, store_path: Path, owner_id: str):
        self.server = server
        self.owner_id = owner_id
        self.store = ConversationInboxStore(store_path)
        self._attached_lock = threading.Lock()
        self._worker_local = threading.local()
        self._ready = threading.Event()
        self._closed = False
        self.attach(sid, session)
        self.planner = FinnConversationPlanner()
        self.runtime = MacManConversationRuntime(
            planner=self.planner,
            current_runtime=self._current_runtime,
            deliver=self._deliver,
            delegate=self._delegate,
            fail_open=self._fail_open,
            conversation_context=self._conversation_context,
            record_turn=self._record_turn,
        )
        self.ingress = ConversationIngress(self.store, owner_id, self._handle)
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(
            target=self._serve,
            daemon=True,
            name=f"macman-conversation-{owner_id[-8:]}",
        )
        self.thread.start()
        if not self._ready.wait(timeout=2):
            raise RuntimeError("conversation loop did not start")

    def attach(self, sid: str, session: dict) -> None:
        with self._attached_lock:
            self.sid = sid
            self.session = session

    def _attached(self) -> tuple[str, dict]:
        with self._attached_lock:
            return self.sid, self.session

    def _serve(self) -> None:
        asyncio.set_event_loop(self.loop)
        task = self.loop.create_task(self.ingress.run())
        self._ingress_task = task
        self._ready.set()
        try:
            self.loop.run_until_complete(task)
        except asyncio.CancelledError:
            pass
        finally:
            self.loop.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.loop.is_running():
            self.loop.call_soon_threadsafe(self._ingress_task.cancel)
        if self.thread.is_alive() and threading.current_thread() is not self.thread:
            self.thread.join(timeout=2)
        self.store.close()

    def accept(self, envelope: dict) -> tuple[dict, bool]:
        if self._closed or not self.loop.is_running():
            raise RuntimeError("conversation actor is unavailable")
        future = asyncio.run_coroutine_threadsafe(self.ingress.enqueue(envelope), self.loop)
        return future.result(timeout=5)

    async def _handle(self, envelope: dict) -> None:
        await self.runtime.handle(envelope)

    def _current_runtime(self) -> dict:
        _sid, session = self._attached()
        agent = session.get("agent")
        if agent is None:
            raise RuntimeError("Hermes agent is not ready")
        return {
            key: getattr(agent, key, None)
            for key in ("model", "provider", "base_url", "api_key", "api_mode")
        }

    def _deliver(self, _text: str) -> None:
        # Delivery is staged by ConversationActionExecutor in its result. The
        # visible event is emitted by _record_turn only after the same turn is
        # committed to Hermes' canonical transcript. Otherwise a renderer
        # refresh between these two operations erases the optimistic message.
        return None

    def _conversation_context(self, _envelope: dict) -> dict:
        return self.store.conversation_context(self.owner_id)

    @staticmethod
    def _turn_content(envelope: dict) -> str:
        text = str(envelope.get("content") or "").strip()
        if text:
            return text
        names = []
        for attachment in envelope.get("attachments", []):
            if not isinstance(attachment, dict):
                continue
            name = attachment.get("name")
            path = attachment.get("path")
            if not isinstance(name, str) or not name.strip():
                name = Path(path).name if isinstance(path, str) and path else "attachment"
            names.append(name.strip())
        return f"[attachments: {', '.join(names)}]"

    @staticmethod
    def _canonical_message_id(message_id: str, role: str) -> str:
        return f"macman-conversation:{role}:{message_id}"

    def _canonical_turn_messages(self, envelope: dict, result: dict) -> list[dict]:
        message_id = str(envelope.get("message_id") or "").strip()
        source = str(envelope.get("source") or "").strip()
        inbound = {
            "role": "user",
            "content": self._turn_content(envelope),
            "platform_message_id": self._canonical_message_id(message_id, source or "user"),
        }
        if source != "user":
            # Worker and trigger envelopes are model context, not words typed by
            # the human. Keep the role alternation Hermes requires while hiding
            # the internal carrier from the visible transcript.
            inbound["display_kind"] = "hidden"

        delivered = [str(text).strip() for text in result.get("delivered", []) if str(text).strip()]
        assistant = {
            "role": "assistant",
            "content": "\n\n".join(delivered),
            "platform_message_id": self._canonical_message_id(message_id, "assistant"),
        }
        if not delivered:
            assistant["display_kind"] = "hidden"
        return [inbound, assistant]

    def _persist_canonical_turn(self, envelope: dict, result: dict) -> bool:
        _sid, session = self._attached()
        agent = session.get("agent")
        session_id = str(getattr(agent, "session_id", None) or session.get("session_key") or "").strip()
        if not session_id:
            raise RuntimeError("MacMan conversation has no canonical Hermes session")
        if not self.server._ensure_session_db_row(session):
            raise RuntimeError("Hermes session database is unavailable")
        self.server._persist_branch_seed(session)

        messages = self._canonical_turn_messages(envelope, result)
        first_message_id = messages[0]["platform_message_id"]
        with self.server._session_db(session) as database:
            if database is None:
                raise RuntimeError("Hermes session database is unavailable")
            if database.has_platform_message_id(session_id, first_message_id):
                return False
            inserted = database.append_messages_batch(session_id, messages)
            if inserted != len(messages):
                raise RuntimeError(
                    f"Hermes persisted {inserted} of {len(messages)} MacMan conversation messages"
                )
            committed = [
                message
                for message in database.get_messages_as_conversation(
                    session_id,
                    include_row_ids=True,
                )
                if message.get("message_id") in {
                    item["platform_message_id"] for item in messages
                }
            ]
        if len(committed) != len(messages):
            raise RuntimeError("Hermes could not reload the committed MacMan conversation turn")

        with session["history_lock"]:
            history = session.setdefault("history", [])
            known_ids = {
                message.get("message_id")
                for message in history
                if isinstance(message, dict)
            }
            history.extend(
                message for message in committed if message.get("message_id") not in known_ids
            )
            session["history_version"] = int(session.get("history_version", 0)) + 1
            if agent is not None:
                agent._session_messages = history
        return True

    def _record_private_turn(self, envelope: dict, result: dict) -> None:
        message_id = str(envelope.get("message_id") or "").strip()
        source = str(envelope.get("source") or "").strip()
        self.store.record_turn(
            self.owner_id,
            role="user",
            source=source,
            message_id=message_id,
            content=self._turn_content(envelope),
        )
        for index, text in enumerate(result.get("delivered", [])):
            self.store.record_turn(
                self.owner_id,
                role="assistant",
                source="system",
                message_id=f"reply:{message_id}:{index}",
                content=text,
            )

    def _record_turn(self, envelope: dict, result: dict) -> None:
        created = self._persist_canonical_turn(envelope, result)
        try:
            self._record_private_turn(envelope, result)
        except Exception:
            # Hermes is the transcript authority. A private Finn context write
            # must not make an already durable user turn disappear.
            logger.warning("failed to update Finn private conversation context", exc_info=True)
        if not created:
            return
        sid, _session = self._attached()
        for text in result.get("delivered", []):
            self.server._emit("message.start", sid)
            self.server._emit("message.complete", sid, {"text": text})

    def _load_worker_history(self, worker_id: str) -> list[dict]:
        return self.store.get_worker_history(self.owner_id, worker_id)

    def _worker_started(self, request: dict, worker_id: str, resumed: bool) -> None:
        if resumed:
            if not self.store.claim_follow_up(self.owner_id, worker_id):
                raise ConversationActionError("worker is no longer available for follow-up")
            return
        self.store.start_worker(
            self.owner_id,
            worker_id,
            task=request["task"],
            origin_message_id=request["origin_message_id"],
        )

    def _settle_worker_result(self, envelope: dict) -> dict:
        sanitized = dict(envelope)
        model_messages = sanitized.pop("_model_messages", None)
        worker_id = str(sanitized.get("worker_id") or "").strip()
        persisted = self.store.finish_worker(
            self.owner_id,
            worker_id,
            status=sanitized.get("status"),
            summary=sanitized.get("content", ""),
            model_messages=model_messages,
        )
        if not persisted:
            raise RuntimeError(f"worker result has no running owner: {worker_id}")
        return sanitized

    def _fail_open(self, envelope: dict) -> None:
        sid, session = self._attached()
        image_paths = [
            item["path"] for item in envelope.get("attachments", [])
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        ]
        if image_paths:
            with session["history_lock"]:
                session.setdefault("attached_images", []).extend(
                    path for path in image_paths if path not in session.get("attached_images", [])
                )
        response = self.server._methods["prompt.submit"](
            f"conversation-fallback:{envelope.get('message_id', '')}",
            {"session_id": sid, "text": envelope.get("content", ""), "queued": True},
        )
        if isinstance(response, dict) and response.get("error"):
            self.server._emit("error", sid, {"message": response["error"].get("message", "Hermes rejected the turn")})

    def _delegate(self, request: dict) -> str:
        sid, session = self._attached()
        parent_agent = session.get("agent")
        if parent_agent is None:
            raise RuntimeError("Hermes agent is not ready")

        @contextlib.contextmanager
        def worker_scope(worker_id: str, worker_request: dict):
            from tools.approval_context import (
                reset_current_request_authorization,
                reset_current_session_key,
                set_current_request_authorization,
                set_current_session_key,
            )

            authorization = worker_request.get("authorization")
            if not isinstance(authorization, dict):
                raise RuntimeError("MacMan worker is missing request authorization")

            request_token = approval_token = session_tokens = None
            try:
                request_token = set_current_request_authorization(
                    source=authorization.get("source"),
                    user_request=authorization.get("user_request"),
                    delegated_task=authorization.get("delegated_task"),
                )
                session_tokens = self.server._set_session_context(
                    worker_id,
                    cwd=self.server._session_cwd(session),
                    ui_session_id=sid,
                )
                # Recoverable command risk is assessed against this request. Approval
                # identity remains the visible session; Hermes' worker identity is separate.
                approval_token = set_current_session_key(str(session.get("session_key") or ""))
                with self.server._session_profile_runtime_scope(session):
                    self.server._wire_callbacks(sid)
                    parent_db = getattr(parent_agent, "_session_db", None)
                    with self.server._side_agent_session_db(parent_db) as worker_db:
                        self._worker_local.db = worker_db
                        yield
            finally:
                self._worker_local.db = None
                if approval_token is not None:
                    reset_current_session_key(approval_token)
                if session_tokens is not None:
                    self.server._clear_session_context(session_tokens)
                if request_token is not None:
                    reset_current_request_authorization(request_token)

        def make_agent(worker_id: str):
            from run_agent import AIAgent

            kwargs = self.server._background_agent_kwargs(parent_agent, worker_id)
            kwargs.update(
                session_db=self._worker_local.db,
                platform=getattr(parent_agent, "platform", None) or self.server._session_source(session),
                **self.server._agent_cbs(sid),
            )
            return AIAgent(**kwargs)

        def build_message(agent, text: str, attachments: list[dict]):
            paths = [
                item["path"] for item in attachments
                if isinstance(item, dict) and isinstance(item.get("path"), str)
            ]
            return self.server._route_turn_images(agent, text, paths) if paths else text

        def on_result(envelope: dict) -> None:
            if self._closed or not self.loop.is_running():
                return
            result = self._settle_worker_result(envelope)
            future = asyncio.run_coroutine_threadsafe(self.ingress.enqueue(result), self.loop)
            with contextlib.suppress(Exception):
                future.result(timeout=5)

        return HermesWorkerBridge(
            make_agent=make_agent,
            worker_scope=worker_scope,
            build_message=build_message,
            on_result=on_result,
            load_history=self._load_worker_history,
            on_started=self._worker_started,
        ).delegate(request)
