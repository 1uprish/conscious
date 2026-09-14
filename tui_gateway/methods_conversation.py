"""MacMan conversation adapter RPC; Hermes prompt.submit remains the fail-open path."""

from __future__ import annotations

import atexit
import os
import sys
import threading
from pathlib import Path

from .method_ctx import HandlerRegistry, bind_module

_registry = HandlerRegistry()
method = _registry.method
_conversation_actors = {}
_conversation_actors_lock = threading.Lock()


def _conversation_actor_for(sid: str, session: dict):
    from hermes_constants import get_hermes_home
    from tui_gateway.macman_conversation_actor import MacManConversationActor

    home = Path(session.get("profile_home") or get_hermes_home()).resolve()
    owner = str(session.get("session_key") or sid)
    key = (str(home), owner)
    with _conversation_actors_lock:
        actor = _conversation_actors.get(key)
        if actor is None:
            actor = MacManConversationActor(
                sys.modules[__name__],
                sid,
                session,
                store_path=home / "macman" / "conversation.sqlite3",
                owner_id=owner,
            )
            _conversation_actors[key] = actor
        else:
            actor.attach(sid, session)
        return actor


def _close_conversation_actors() -> None:
    with _conversation_actors_lock:
        actors = list(_conversation_actors.values())
        _conversation_actors.clear()
    for actor in actors:
        actor.close()


@method("conversation.submit")
def _(rid, params: dict) -> dict:
    from hermes_cli.input_sanitize import sanitize_user_prompt_text

    sid = params.get("session_id", "")
    text = sanitize_user_prompt_text(params.get("text", ""))
    message_id = str(params.get("client_message_id") or "").strip()
    if not text.strip():
        return _err(rid, 4002, "text required")
    if not message_id:
        return _err(rid, 4002, "client_message_id required")
    session, err = _sess_nowait(params, rid)
    if err:
        return err
    with session["history_lock"]:
        image_paths = list(session.get("attached_images", []))
    attachments = [
        {"kind": "image", "name": os.path.basename(path), "path": path}
        for path in image_paths
    ]
    envelope = {
        "source": "user",
        "channel": "desktop",
        "thread_id": str(session.get("session_key") or sid),
        "message_id": message_id,
        "content": text,
        "attachments": attachments,
    }
    try:
        receipt, created = _conversation_actor_for(sid, session).accept(envelope)
    except (RuntimeError, ValueError, TimeoutError) as exc:
        logger.warning("conversation.submit admission failed: %s", exc, exc_info=True)
        return _err(rid, 5034, "conversation admission failed")
    if created and image_paths:
        with session["history_lock"]:
            current = list(session.get("attached_images", []))
            session["attached_images"] = [path for path in current if path not in image_paths]
    return _ok(rid, {
        "status": "accepted",
        "client_message_id": message_id,
        "dispatch_id": str(receipt["id"]),
    })


def register(server) -> None:
    bind_module(globals(), server, skip=("_",))
    atexit.register(server._close_conversation_actors)
