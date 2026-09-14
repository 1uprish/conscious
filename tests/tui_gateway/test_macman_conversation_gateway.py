"""Gateway admission contracts for the MacMan conversational adapter."""

from __future__ import annotations

import threading

from tui_gateway import server


class FakeActor:
    def __init__(self, *, created=True):
        self.created = created
        self.calls = []

    def accept(self, envelope):
        self.calls.append(envelope)
        return ({"id": 17, "state": "accepted"}, self.created)


def _session(images=None):
    ready = threading.Event()
    ready.set()
    return {
        "agent": object(),
        "agent_ready": ready,
        "attached_images": list(images or []),
        "history_lock": threading.RLock(),
        "session_key": "stored-chat",
        "source": "desktop",
    }


def test_conversation_submit_accepts_exact_text_and_claims_staged_images(monkeypatch):
    actor = FakeActor()
    session = _session(["/tmp/one.png"])
    monkeypatch.setitem(server._sessions, "live-chat", session)
    monkeypatch.setattr(server, "_conversation_actor_for", lambda _sid, _session: actor)

    response = server._methods["conversation.submit"]("request-one", {
        "session_id": "live-chat",
        "text": "look at this exactly",
        "client_message_id": "client-one",
    })

    assert response["result"] == {
        "status": "accepted",
        "client_message_id": "client-one",
        "dispatch_id": "17",
    }
    assert actor.calls == [{
        "source": "user",
        "channel": "desktop",
        "thread_id": "stored-chat",
        "message_id": "client-one",
        "content": "look at this exactly",
        "attachments": [{"kind": "image", "name": "one.png", "path": "/tmp/one.png"}],
    }]
    assert session["attached_images"] == []


def test_duplicate_transport_retry_does_not_claim_newly_staged_images(monkeypatch):
    actor = FakeActor(created=False)
    session = _session(["/tmp/new.png"])
    monkeypatch.setitem(server._sessions, "live-chat", session)
    monkeypatch.setattr(server, "_conversation_actor_for", lambda _sid, _session: actor)

    response = server._methods["conversation.submit"]("request-two", {
        "session_id": "live-chat",
        "text": "same",
        "client_message_id": "client-one",
    })

    assert response["result"]["status"] == "accepted"
    assert session["attached_images"] == ["/tmp/new.png"]


def test_conversation_submit_rejects_empty_or_missing_message_identity(monkeypatch):
    monkeypatch.setitem(server._sessions, "live-chat", _session())

    empty = server._methods["conversation.submit"]("empty", {
        "session_id": "live-chat", "text": "", "client_message_id": "one",
    })
    missing_id = server._methods["conversation.submit"]("missing", {
        "session_id": "live-chat", "text": "hey", "client_message_id": "",
    })

    assert empty["error"]["code"] == 4002
    assert missing_id["error"]["code"] == 4002


def test_conversation_submit_never_blocks_the_gateway_reader():
    assert "conversation.submit" in server._LONG_HANDLERS
