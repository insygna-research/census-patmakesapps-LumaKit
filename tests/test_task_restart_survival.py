"""§6.3 durable state proven: a task survives a backend restart.

Simulates the flagship claim end-to-end at the runner level:

1. A first TaskRunner drives the task — the model makes real progress
   (update_todos) and then the process "dies" mid-task (LLM error →
   checkpoint + retry scheduling).
2. A brand-new TaskRunner instance (fresh caches = new process) picks the
   task up from the persisted session on its next tick.
3. The model in the new process receives the FULL prior thread — the same
   system prompt, kickoff, and its own earlier tool calls — and finishes.

No real LLM, registry, or network: the model is scripted.
"""

from datetime import datetime

import pytest

import core.task_store as ts
from core.task_runner import TaskRunner


class ScriptedLLM:
    """Stands in for any provider client: returns scripted rounds, raises
    scripted exceptions, records every thread it was called with."""

    def __init__(self, script):
        self.script = list(script)
        self.threads = []
        self.fallback_model = None

    def tags(self, request_timeout=None):  # _probe_ollama health probe
        return {}

    def chat(self, model, messages, **kwargs):
        self.threads.append([dict(m) for m in messages])
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return {"message": step}


def _tool_call(name, arguments):
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": name, "arguments": arguments}}],
    }


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "DB_PATH", tmp_path / "tasks.db")
    return ts


def _make_runner(monkeypatch, llm, notifications, tmp_path):
    runner = TaskRunner(notify=lambda msg, cid: notifications.append(msg))
    monkeypatch.setattr(runner, "_get_ollama", lambda: llm)
    monkeypatch.setattr(runner, "_get_registry", lambda: None)
    monkeypatch.setattr(runner, "_build_tool_list", lambda registry: [])
    monkeypatch.setattr(
        runner, "_model_config",
        lambda owner_chat_id=None: {"primary_model": "scripted", "fallback_model": None},
    )
    monkeypatch.setattr(
        runner, "_resolve_task_workspace_or_fallback", lambda task: tmp_path
    )
    return runner


def test_task_survives_restart(store, tmp_path, monkeypatch):
    notifications = []
    task_id = store.create_task(
        title="build the landing page",
        goal="write index.html and verify it renders",
        owner_chat_id="owner",
        workspace_path=str(tmp_path),
    )

    # --- Process 1: makes progress, then the runtime dies mid-task -------
    llm1 = ScriptedLLM([
        _tool_call("update_todos", {"todos": [
            {"description": "write index.html", "status": "in_progress"},
        ]}),
        ConnectionError("model runtime went away (simulated crash)"),
    ])
    runner1 = _make_runner(monkeypatch, llm1, notifications, tmp_path)
    runner1._tick()

    persisted = store.get_task(task_id)
    assert persisted["status"] == "active"
    # progress was checkpointed before the failure
    assert persisted["plan"] and persisted["plan"][0]["description"] == "write index.html"
    roles = [m.get("role") for m in persisted["messages"]]
    assert roles[0] == "system" and "assistant" in roles and "tool" in roles
    # the failure was recorded honestly, with a scheduled retry
    assert any(e["type"] == "step_retry" for e in persisted["history"])
    assert int(persisted["constraints"]["_runtime_retries"]) == 1

    # --- "Restart": a brand-new runner instance, fresh caches ------------
    # The retry backoff put next_run_at in the future; pretend it elapsed.
    store.update_task(task_id, next_run_at=datetime.now().isoformat())

    llm2 = ScriptedLLM([
        _tool_call("finish_task", {
            "outcome": "done",
            "report": "Landing page written and verified after restart.",
        }),
    ])
    runner2 = _make_runner(monkeypatch, llm2, notifications, tmp_path)
    runner2._tick()

    # The new process resumed from the persisted thread with full context…
    resumed_thread = llm2.threads[0]
    assert resumed_thread[0]["role"] == "system"
    assert any("GOAL: write index.html" in (m.get("content") or "") for m in resumed_thread)
    assert any(
        (m.get("tool_calls") or [{}])[0].get("function", {}).get("name") == "update_todos"
        for m in resumed_thread if m.get("role") == "assistant"
    )

    # …and drove the task to a real completion.
    final = store.get_task(task_id)
    assert final["status"] == "done"
    assert "after restart" in (final["result"] or "")
    assert any("Task complete" in n for n in notifications)
    # the transient retry marker was cleared once progress resumed
    assert not final["constraints"].get("_runtime_retries")


def test_restart_does_not_replay_completed_work(store, tmp_path, monkeypatch):
    """A task finished before the restart must stay finished — the new
    runner's tick must not pick it up again."""
    notifications = []
    task_id = store.create_task(
        title="one shot", goal="do the thing", owner_chat_id="owner",
        workspace_path=str(tmp_path),
    )
    llm1 = ScriptedLLM([
        _tool_call("finish_task", {"outcome": "done", "report": "done in one"}),
    ])
    runner1 = _make_runner(monkeypatch, llm1, notifications, tmp_path)
    runner1._tick()
    assert store.get_task(task_id)["status"] == "done"

    llm2 = ScriptedLLM([])  # any chat() call would IndexError
    runner2 = _make_runner(monkeypatch, llm2, notifications, tmp_path)
    runner2._tick()
    assert llm2.threads == []
    assert store.get_task(task_id)["status"] == "done"
