"""D-1/D-3: tool-result compaction rules."""

import json

from core.history_compaction import (
    TOOL_HISTORY_MAX_CHARS,
    compact_tool_message_content,
    compact_tool_result_for_history,
)


def test_small_results_pass_through():
    result = {"success": True, "data": {"content": "hello"}}
    out = compact_tool_result_for_history("read_file", result)
    assert json.loads(out) == result


def test_oversized_content_truncated():
    result = {"success": True, "data": {"content": "x" * 50_000}}
    out = compact_tool_result_for_history("read_file", result)
    assert len(out) <= TOOL_HISTORY_MAX_CHARS + 100
    assert "truncated" in out


def test_budget_parameterized():
    result = {"success": True, "data": {"content": "y" * 5_000}}
    tight = compact_tool_result_for_history("read_file", result, max_chars=1000)
    loose = compact_tool_result_for_history("read_file", result, max_chars=100_000)
    assert len(tight) <= 1100
    assert len(loose) > len(tight)  # same rules, different budget


def test_error_preserved_in_fallback():
    result = {"success": False, "error": "boom " * 2000, "data": {"content": "z" * 20_000}}
    out = compact_tool_result_for_history("execute_shell", result)
    assert "boom" in out
    assert len(out) <= TOOL_HISTORY_MAX_CHARS + 100


def test_recompact_existing_message():
    original = json.dumps({"success": True, "data": {"content": "w" * 50_000}})
    out = compact_tool_message_content("read_file", original)
    assert len(out) <= TOOL_HISTORY_MAX_CHARS + 100


def test_non_json_content_truncated_not_crashed():
    out = compact_tool_message_content("read_file", "plain text " * 5000)
    assert len(out) <= TOOL_HISTORY_MAX_CHARS + 100
