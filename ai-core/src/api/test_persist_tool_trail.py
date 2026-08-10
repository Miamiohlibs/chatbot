"""The socket handler's tool-trail persistence.

Lifted out of `_v2_message` so it can be exercised without a socket. The
property that matters is not "it writes rows" but "it never costs the
student their answer": the turn has already been delivered by the time
this runs, so every failure here must be swallowed.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent.parent))

import pytest  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def calls(monkeypatch):
    """Capture what would be written, without a database."""
    seen: list[dict] = []

    async def fake_log(conversation_id, *, agent_name, tool_name,
                       parameters, success, execution_time=0):
        seen.append({
            "conversation_id": conversation_id, "agent_name": agent_name,
            "tool_name": tool_name, "parameters": parameters,
            "success": success, "execution_time": execution_time,
        })

    import src.memory.conversation_store as store
    monkeypatch.setattr(store, "log_tool_execution", fake_log)
    return seen


def _persist():
    from src.main import persist_tool_trail
    return persist_tool_trail


def test_each_tool_call_becomes_a_row(calls):
    wire = {"tools_called": [
        {"tool": "search_kb", "agent": "agent", "success": True,
         "latency_ms": 42, "arg_keys": ["query"], "detail": ""},
        {"tool": "get_hours", "agent": "orchestrator", "success": False,
         "latency_ms": 7, "arg_keys": ["campus", "library"],
         "detail": "libcal timeout"},
    ]}
    assert _run(_persist()("conv-1", wire)) == 2
    assert [c["tool_name"] for c in calls] == ["search_kb", "get_hours"]
    assert calls[0]["conversation_id"] == "conv-1"
    assert calls[1]["agent_name"] == "orchestrator"
    assert calls[1]["success"] is False
    assert calls[1]["execution_time"] == 7
    assert calls[1]["parameters"]["detail"] == "libcal timeout"


def test_argument_values_never_reach_the_database(calls):
    """These rows are rendered to library staff. A book_room call carries
    a patron's name and email."""
    wire = {"tools_called": [{
        "tool": "book_room", "agent": "agent", "success": True,
        "latency_ms": 1, "arg_keys": ["patron_email", "room_id"],
    }]}
    _run(_persist()("conv-1", wire))
    stored = repr(calls[0]["parameters"])
    assert "patron_email" in stored
    assert "@" not in stored, stored


def test_a_turn_with_no_tools_writes_nothing(calls):
    for wire in ({}, {"tools_called": []}, {"tools_called": None}):
        assert _run(_persist()("conv-1", wire)) == 0
    assert calls == []


def test_a_malformed_row_is_skipped_not_fatal(calls):
    wire = {"tools_called": [
        "not-a-dict",
        None,
        {"tool": "get_hours", "success": 1, "latency_ms": "9"},
    ]}
    assert _run(_persist()("conv-1", wire)) == 1
    assert calls[0]["tool_name"] == "get_hours"
    assert calls[0]["success"] is True
    assert calls[0]["execution_time"] == 9


def test_a_row_missing_its_names_still_writes_something_usable(calls):
    _run(_persist()("conv-1", {"tools_called": [{"success": True}]}))
    assert calls[0]["tool_name"] == "unknown"
    assert calls[0]["agent_name"] == "orchestrator"
    assert calls[0]["execution_time"] == 0


def test_one_failing_row_does_not_stop_the_rest(monkeypatch):
    seen: list[str] = []

    async def flaky(conversation_id, *, tool_name, **kw):
        if tool_name == "boom":
            raise RuntimeError("unique constraint")
        seen.append(tool_name)

    import src.memory.conversation_store as store
    monkeypatch.setattr(store, "log_tool_execution", flaky)

    wire = {"tools_called": [
        {"tool": "first", "success": True},
        {"tool": "boom", "success": True},
        {"tool": "third", "success": True},
    ]}
    assert _run(_persist()("conv-1", wire)) == 2
    assert seen == ["first", "third"]


def test_a_database_outage_never_reaches_the_student(monkeypatch):
    """The reply was emitted before this runs. Losing telemetry is
    acceptable; raising into the handler is not."""
    import src.memory.conversation_store as store

    async def dead(*a, **k):
        raise ConnectionError("postgres is down")

    monkeypatch.setattr(store, "log_tool_execution", dead)
    assert _run(_persist()("conv-1", {"tools_called": [
        {"tool": "search_kb", "success": True}]})) == 0
