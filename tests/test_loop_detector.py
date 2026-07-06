"""R-4: loop detector counts failures, not successes."""

import pytest

agent_mod = pytest.importorskip("agent")


@pytest.fixture()
def bare_agent():
    # Detector state doesn't need the full (heavy) Agent constructor.
    a = agent_mod.Agent.__new__(agent_mod.Agent)
    a._attempt_counts = {}
    return a


def _fail(a, tool, inputs):
    a._record_tool_outcome(tool, inputs, {"success": False, "error": "nope"})


def _succeed(a, tool, inputs):
    a._record_tool_outcome(tool, inputs, {"success": True, "data": {}})


def test_successful_repeats_never_abort(bare_agent):
    a = bare_agent
    for _ in range(5):
        assert a._register_tool_attempt("read_file", {"path": "x.txt"}) is None
        _succeed(a, "read_file", {"path": "x.txt"})


def test_three_failures_abort(bare_agent):
    a = bare_agent
    for _ in range(3):
        assert a._register_tool_attempt("read_file", {"path": "bad.txt"}) is None
        _fail(a, "read_file", {"path": "bad.txt"})
    assert a._register_tool_attempt("read_file", {"path": "bad.txt"}) is not None


def test_success_resets_counter(bare_agent):
    a = bare_agent
    for _ in range(2):
        _fail(a, "read_file", {"path": "flaky.txt"})
    _succeed(a, "read_file", {"path": "flaky.txt"})
    for _ in range(2):
        _fail(a, "read_file", {"path": "flaky.txt"})
    assert a._register_tool_attempt("read_file", {"path": "flaky.txt"}) is None


def test_user_declines_count_as_no_progress(bare_agent):
    a = bare_agent
    for _ in range(3):
        a._record_tool_outcome(
            "execute_shell", {"command": "mv a b"},
            {"success": True, "data": {"skipped": True}},
        )
    assert a._register_tool_attempt("execute_shell", {"command": "mv a b"}) is not None
