"""LumaKit renews and clears LumaBot thinking leases safely."""

import threading

from tools.lumabot.activity import LumaBotActivityLease


def test_disabled_activity_makes_no_requests():
    calls = []
    lease = LumaBotActivityLease(
        enabled=False,
        request_fn=lambda *args: calls.append(args),
    )
    lease.start()
    lease.close()
    assert calls == []


def test_activity_renews_and_clears_its_unique_lease():
    calls = []
    renewed = threading.Event()

    def record(lease_id, active, ttl_s):
        calls.append((lease_id, active, ttl_s))
        if sum(1 for call in calls if call[1]) >= 2:
            renewed.set()

    lease = LumaBotActivityLease(
        enabled=True,
        ttl_s=10,
        renew_s=0.01,
        request_fn=record,
        lease_id="run-a",
    )
    lease.start()
    assert renewed.wait(1.0)
    lease.close()

    assert calls[0] == ("run-a", True, 10)
    assert calls[-1] == ("run-a", False, 10)


def test_agent_closes_activity_after_success(workspace, monkeypatch):
    import agent as agent_module

    events = []

    class FakeLease:
        def start(self):
            events.append("start")

        def close(self):
            events.append("close")

    class FakeModel:
        last_model_used = "fake"

        def chat(self, **kwargs):
            return {"message": {"role": "assistant", "content": "Done."}}

    monkeypatch.setattr(agent_module, "LumaBotActivityLease", FakeLease)
    agent = agent_module.Agent(enable_spinner=False)
    agent.ollama = FakeModel()
    agent.model = "fake"

    response = agent.ask_llm("hello")

    assert response["message"]["content"] == "Done."
    assert events == ["start", "close"]


def test_agent_closes_activity_when_interrupted(workspace, monkeypatch):
    import agent as agent_module

    events = []

    class FakeLease:
        def start(self):
            events.append("start")

        def close(self):
            events.append("close")

    class ModelMustNotRun:
        def chat(self, **kwargs):
            raise AssertionError("model should not run after an interrupt")

    monkeypatch.setattr(agent_module, "LumaBotActivityLease", FakeLease)
    agent = agent_module.Agent(
        check_interrupt=lambda: True,
        enable_spinner=False,
    )
    agent.ollama = ModelMustNotRun()

    response = agent.ask_llm("stop immediately")

    assert response["message"]["content"] == "Stopped."
    assert events == ["start", "close"]


def test_agent_closes_activity_after_model_failure(workspace, monkeypatch):
    import agent as agent_module

    events = []

    class FakeLease:
        def start(self):
            events.append("start")

        def close(self):
            events.append("close")

    class BrokenModel:
        last_model_used = None

        def chat(self, **kwargs):
            raise RuntimeError("model failed")

    monkeypatch.setattr(agent_module, "LumaBotActivityLease", FakeLease)
    agent = agent_module.Agent(enable_spinner=False)
    agent.ollama = BrokenModel()

    response = agent.ask_llm("hello")

    assert "model failed" in response["message"]["content"]
    assert events == ["start", "close"]
