"""Live actor contracts for Finn-style continuity over Hermes workers."""

from __future__ import annotations

import pytest

from tui_gateway.macman_conversation_actions import ConversationActionError
from tui_gateway.macman_conversation_actor import MacManConversationActor


class RecordingStore:
    def __init__(self):
        self.calls = []
        self.context = {
            "messages": [{"role": "user", "content": "open Notes"}],
            "active_workers": [],
            "follow_up_workers": [],
        }
        self.history = [{"role": "assistant", "content": "Which note?"}]
        self.follow_up_allowed = True

    def conversation_context(self, owner_id):
        self.calls.append(("context", owner_id))
        return self.context

    def record_turn(self, owner_id, **kwargs):
        self.calls.append(("record", owner_id, kwargs))
        return True

    def start_worker(self, owner_id, worker_id, **kwargs):
        self.calls.append(("start", owner_id, worker_id, kwargs))

    def claim_follow_up(self, owner_id, worker_id):
        self.calls.append(("claim", owner_id, worker_id))
        return self.follow_up_allowed

    def get_worker_history(self, owner_id, worker_id):
        self.calls.append(("history", owner_id, worker_id))
        return self.history

    def finish_worker(self, owner_id, worker_id, **kwargs):
        self.calls.append(("finish", owner_id, worker_id, kwargs))
        return True


def _actor(store=None):
    actor = MacManConversationActor.__new__(MacManConversationActor)
    actor.owner_id = "owner-one"
    actor.store = store or RecordingStore()
    return actor


def test_actor_records_the_inbound_turn_and_each_visible_reply_idempotently():
    actor = _actor()
    envelope = {
        "source": "user",
        "message_id": "message-one",
        "content": "",
        "attachments": [
            {"name": "note.txt", "path": "/tmp/note.txt"},
            {"path": "/tmp/image.png"},
        ],
    }

    actor._record_turn(envelope, {"delivered": ["got it", "the note is open"]})

    assert actor.store.calls == [
        ("record", "owner-one", {
            "role": "user",
            "source": "user",
            "message_id": "message-one",
            "content": "[attachments: note.txt, image.png]",
        }),
        ("record", "owner-one", {
            "role": "assistant",
            "source": "system",
            "message_id": "reply:message-one:0",
            "content": "got it",
        }),
        ("record", "owner-one", {
            "role": "assistant",
            "source": "system",
            "message_id": "reply:message-one:1",
            "content": "the note is open",
        }),
    ]


def test_actor_exposes_private_context_and_resumes_only_an_owned_live_follow_up():
    actor = _actor()

    assert actor._conversation_context({}) is actor.store.context
    assert actor._load_worker_history("worker-one") is actor.store.history

    request = {"task": "open the project note", "origin_message_id": "message-two"}
    actor._worker_started(request, "worker-new", False)
    actor._worker_started(request, "worker-one", True)

    assert actor.store.calls == [
        ("context", "owner-one"),
        ("history", "owner-one", "worker-one"),
        ("start", "owner-one", "worker-new", {
            "task": "open the project note",
            "origin_message_id": "message-two",
        }),
        ("claim", "owner-one", "worker-one"),
    ]

    actor.store.follow_up_allowed = False
    with pytest.raises(ConversationActionError, match="no longer available"):
        actor._worker_started(request, "worker-one", True)


def test_actor_persists_worker_history_before_returning_a_sanitized_result():
    actor = _actor()
    model_messages = [
        {"role": "user", "content": "open Notes"},
        {"role": "assistant", "content": "Notes is open"},
    ]
    envelope = {
        "source": "worker",
        "worker_id": "worker-one",
        "status": "complete",
        "content": "Notes is open",
        "_model_messages": model_messages,
    }

    sanitized = actor._settle_worker_result(envelope)

    assert actor.store.calls == [
        ("finish", "owner-one", "worker-one", {
            "status": "complete",
            "summary": "Notes is open",
            "model_messages": model_messages,
        }),
    ]
    assert sanitized == {
        "source": "worker",
        "worker_id": "worker-one",
        "status": "complete",
        "content": "Notes is open",
    }
    assert "_model_messages" in envelope

