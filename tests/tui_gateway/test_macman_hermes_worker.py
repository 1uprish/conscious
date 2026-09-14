"""Hermes worker isolation contracts behind the Finn conversational layer."""

from __future__ import annotations

import threading

from tui_gateway.macman_hermes_worker import HermesWorkerBridge


class ControlledThread:
    def __init__(self, target):
        self.target = target
        self.started = False

    def start(self):
        self.started = True


class FakeAgent:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []
        self.stream_delta_callback = lambda _text: None
        self.interim_assistant_callback = lambda _text: None
        self.closed = False

    def run_conversation(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result

    def close(self):
        self.closed = True


def _request():
    return {
        "task": "Open Notes",
        "context": "Use the current Mac",
        "user_content": "open Notes please",
        "attachments": [{"name": "note.txt", "path": "/tmp/note.txt"}],
        "origin_message_id": "user-one",
        "channel": "desktop",
        "thread_id": "chat-one",
    }


def test_delegate_returns_immediately_then_runs_exact_request_in_an_isolated_hermes_worker():
    threads = []
    agents = []
    entered = []
    results = []

    class Scope:
        def __enter__(self):
            entered.append("enter")

        def __exit__(self, *_args):
            entered.append("exit")

    def make_agent(worker_id):
        agent = FakeAgent({"final_response": "Notes is open"})
        agents.append((worker_id, agent))
        return agent

    bridge = HermesWorkerBridge(
        make_agent=make_agent,
        worker_scope=lambda _worker_id: Scope(),
        build_message=lambda agent, text, attachments: {
            "text": text,
            "paths": [item["path"] for item in attachments],
            "agent": agent,
        },
        on_result=results.append,
        thread_factory=lambda target: threads.append(ControlledThread(target)) or threads[-1],
        id_factory=lambda: "worker-one",
    )

    worker_id = bridge.delegate(_request())

    assert worker_id == "worker-one"
    assert threads[0].started is True
    assert agents == []

    threads[0].target()

    assert entered == ["enter", "exit"]
    assert agents[0][0] == "worker-one"
    agent = agents[0][1]
    assert agent.stream_delta_callback is None
    assert agent.interim_assistant_callback is None
    assert agent.calls == [{
        "user_message": {"text": "open Notes please", "paths": ["/tmp/note.txt"], "agent": agent},
        "task_id": "worker-one",
    }]
    assert agent.closed is True
    assert results == [{
        "source": "worker",
        "channel": "desktop",
        "thread_id": "chat-one",
        "message_id": "worker-one:complete:user-one",
        "content": "Notes is open",
        "attachments": [],
        "worker_id": "worker-one",
        "origin_message_id": "user-one",
        "status": "complete",
    }]


def test_worker_failure_is_a_truthful_internal_result_not_a_false_completion():
    result_ready = threading.Event()
    results = []

    class Scope:
        def __enter__(self):
            return None

        def __exit__(self, *_args):
            return None

    bridge = HermesWorkerBridge(
        make_agent=lambda _worker_id: FakeAgent(error=RuntimeError("provider unavailable")),
        worker_scope=lambda _worker_id: Scope(),
        build_message=lambda _agent, text, _attachments: text,
        on_result=lambda result: (results.append(result), result_ready.set()),
        id_factory=lambda: "worker-failed",
    )

    bridge.delegate(_request())
    assert result_ready.wait(timeout=2)

    assert results[0]["status"] == "failed"
    assert results[0]["message_id"] == "worker-failed:failed:user-one"
    assert "provider unavailable" in results[0]["content"]
    assert "completed" not in results[0]["content"].lower()


def test_empty_hermes_final_is_reported_as_failure_instead_of_inventing_success():
    results = []
    threads = []

    class Scope:
        def __enter__(self):
            return None

        def __exit__(self, *_args):
            return None

    bridge = HermesWorkerBridge(
        make_agent=lambda _worker_id: FakeAgent({"final_response": "  "}),
        worker_scope=lambda _worker_id: Scope(),
        build_message=lambda _agent, text, _attachments: text,
        on_result=results.append,
        thread_factory=lambda target: threads.append(ControlledThread(target)) or threads[-1],
        id_factory=lambda: "worker-empty",
    )

    bridge.delegate(_request())
    threads[0].target()

    assert results[0]["status"] == "failed"
    assert results[0]["content"] == "Hermes finished without a result."


def test_completed_worker_follow_up_resumes_the_same_hermes_transcript():
    threads = []
    agents = []
    started = []
    results = []
    prior = [
        {"role": "user", "content": "open Notes"},
        {"role": "assistant", "content": "Which note should I open?"},
    ]

    class Scope:
        def __enter__(self):
            return None

        def __exit__(self, *_args):
            return None

    def make_agent(worker_id):
        agent = FakeAgent({
            "final_response": "The project note is open",
            "messages": [
                *prior,
                {"role": "user", "content": "open Notes please"},
                {"role": "assistant", "content": "The project note is open"},
            ],
        })
        agents.append((worker_id, agent))
        return agent

    bridge = HermesWorkerBridge(
        make_agent=make_agent,
        worker_scope=lambda _worker_id: Scope(),
        build_message=lambda _agent, text, _attachments: text,
        load_history=lambda worker_id: prior if worker_id == "worker-one" else [],
        on_started=lambda request, worker_id, resumed: started.append((request, worker_id, resumed)),
        on_result=results.append,
        thread_factory=lambda target: threads.append(ControlledThread(target)) or threads[-1],
        id_factory=lambda: (_ for _ in ()).throw(AssertionError("must reuse worker id")),
    )
    request = {**_request(), "worker_id": "worker-one", "origin_message_id": "user-two"}

    assert bridge.delegate(request) == "worker-one"
    assert started == [(request, "worker-one", True)]
    threads[0].target()

    assert agents[0][1].calls == [{
        "user_message": "open Notes please",
        "task_id": "worker-one",
        "conversation_history": prior,
    }]
    assert results[0]["message_id"] == "worker-one:complete:user-two"
    assert results[0]["_model_messages"][-1] == {
        "role": "assistant", "content": "The project note is open",
    }
