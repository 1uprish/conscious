"""Live actor contracts for Finn-style continuity over Hermes workers."""

from __future__ import annotations

import contextlib
import threading
from types import SimpleNamespace

import pytest

from hermes_state import SessionDB
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


class CanonicalServer:
    def __init__(self, database):
        self.database = database
        self.events = []

    def _ensure_session_db_row(self, session):
        self.database.create_session(session["session_key"], source="desktop")
        return True

    def _persist_branch_seed(self, _session):
        return None

    @contextlib.contextmanager
    def _session_db(self, _session):
        yield self.database

    def _emit(self, event, sid, payload=None):
        # Delivery must happen only after the turn is durable. A renderer can
        # reconcile at any event boundary, including immediately on message.start.
        durable = self.database.get_messages_as_conversation("stored-chat", include_row_ids=True)
        self.events.append((event, sid, payload, [(item["role"], item["content"]) for item in durable]))


def _canonical_actor(tmp_path):
    database = SessionDB(tmp_path / "state.db")
    actor = _actor()
    actor.server = CanonicalServer(database)
    actor._attached_lock = threading.Lock()
    history = []
    session = {
        "agent": SimpleNamespace(session_id="stored-chat", _session_messages=history),
        "history": history,
        "history_lock": threading.RLock(),
        "history_version": 0,
        "session_key": "stored-chat",
        "source": "desktop",
    }
    actor.attach("live-chat", session)
    return actor, database, session


def test_actor_commits_finn_turn_to_hermes_before_visible_delivery(tmp_path):
    actor, database, session = _canonical_actor(tmp_path)
    envelope = {
        "source": "user",
        "message_id": "user-client-one",
        "content": "yo",
        "attachments": [],
    }

    actor._deliver("hey, what's up?")
    assert actor.server.events == []

    actor._record_turn(envelope, {"delivered": ["hey, what's up?"]})

    durable = database.get_messages_as_conversation("stored-chat", include_row_ids=True)
    assert [(item["role"], item["content"]) for item in durable] == [
        ("user", "yo"),
        ("assistant", "hey, what's up?"),
    ]
    assert session["history"] == durable
    assert session["agent"]._session_messages is session["history"]
    assert session["history_version"] == 1
    assert actor.server.events == [
        ("message.start", "live-chat", None, [("user", "yo"), ("assistant", "hey, what's up?")]),
        (
            "message.complete",
            "live-chat",
            {"text": "hey, what's up?"},
            [("user", "yo"), ("assistant", "hey, what's up?")],
        ),
    ]


def test_actor_replay_does_not_duplicate_or_redeliver_a_committed_finn_turn(tmp_path):
    actor, database, session = _canonical_actor(tmp_path)
    envelope = {
        "source": "user",
        "message_id": "user-client-one",
        "content": "yo",
        "attachments": [],
    }
    result = {"delivered": ["hey, what's up?"]}

    actor._record_turn(envelope, result)
    actor._record_turn(envelope, result)

    durable = database.get_messages_as_conversation("stored-chat", include_row_ids=True)
    assert [(item["role"], item["content"]) for item in durable] == [
        ("user", "yo"),
        ("assistant", "hey, what's up?"),
    ]
    assert session["history_version"] == 1
    assert [event[0] for event in actor.server.events] == ["message.start", "message.complete"]


def test_actor_keeps_worker_input_internal_while_persisting_its_finn_reply(tmp_path):
    actor, database, _session = _canonical_actor(tmp_path)
    envelope = {
        "source": "worker",
        "message_id": "worker-one:complete:user-client-one",
        "content": "Notes is open with the project note selected.",
        "attachments": [],
    }

    actor._record_turn(envelope, {"delivered": ["done, project note's open"]})

    durable = database.get_messages_as_conversation("stored-chat", include_row_ids=True)
    assert [item["role"] for item in durable] == ["user", "assistant"]
    assert durable[0]["display_kind"] == "hidden"
    assert durable[1]["content"] == "done, project note's open"
    assert actor.server.events[-1][2] == {"text": "done, project note's open"}


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

    actor._record_private_turn(envelope, {"delivered": ["got it", "the note is open"]})

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
