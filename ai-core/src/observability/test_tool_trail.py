"""Tests for the per-turn tool trail.

The trail feeds the admin review ticket's "Tools called" table, which is
what an operator opens first when a librarian reports a bad answer -- so
the failure mode that matters is not "it crashed" but "it quietly
recorded the wrong turn's tools, or none at all".
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent.parent))

from src.observability import tool_trail as tt  # noqa: E402


def test_nothing_is_recorded_until_a_turn_begins():
    """dispatch() is called by unit tests and the eval harness with no
    turn around it. That must be a no-op, not an error and not a buffer
    that grows for the lifetime of the process."""
    tt._TRAIL.set(None)
    tt.record(tool="search_kb", success=True, latency_ms=5)
    assert tt.collected() == []


def test_a_recorded_call_comes_back_in_dispatch_order():
    tt.begin_turn()
    tt.record(tool="get_hours", success=True, latency_ms=12)
    tt.record(tool="search_kb", success=False, latency_ms=340, detail="boom")
    rows = tt.collected()
    assert [r["tool"] for r in rows] == ["get_hours", "search_kb"]
    assert rows[0]["success"] is True and rows[1]["success"] is False
    assert rows[1]["latency_ms"] == 340
    assert rows[1]["detail"] == "boom"


def test_begin_turn_clears_the_previous_turn():
    """THE reason begin_turn exists. run_turn executes on a pooled
    executor thread and those threads are reused, so without a reset the
    second turn on a given thread reports the first turn's tools -- and
    an operator reviewing a bad answer would be looking at a different
    conversation's evidence."""
    tt.begin_turn()
    tt.record(tool="from_turn_one", success=True, latency_ms=1)
    assert len(tt.collected()) == 1

    tt.begin_turn()
    assert tt.collected() == []
    tt.record(tool="from_turn_two", success=True, latency_ms=1)
    assert [r["tool"] for r in tt.collected()] == ["from_turn_two"]


def test_a_reused_worker_thread_does_not_leak_between_turns():
    """The same property, exercised through the mechanism that actually
    bites: one worker thread serving two turns in sequence."""
    def turn(name: str) -> list[str]:
        tt.begin_turn()
        tt.record(tool=name, success=True, latency_ms=1)
        return [r["tool"] for r in tt.collected()]

    with ThreadPoolExecutor(max_workers=1) as pool:   # forces reuse
        first = pool.submit(turn, "turn_one").result()
        second = pool.submit(turn, "turn_two").result()

    assert first == ["turn_one"]
    assert second == ["turn_two"], "the second turn inherited the first's trail"


def test_concurrent_turns_keep_separate_trails():
    def turn(name: str) -> list[str]:
        tt.begin_turn()
        for i in range(20):
            tt.record(tool=f"{name}_{i}", success=True, latency_ms=1)
        return [r["tool"] for r in tt.collected()]

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(turn, ["a", "b", "c", "d"]))

    for name, rows in zip(["a", "b", "c", "d"], results):
        assert len(rows) == 20
        assert all(r.startswith(name + "_") for r in rows), rows


def test_the_phase_says_which_stage_dispatched():
    """A reviewer needs to tell an agent-loop call from one of the
    orchestrator's short-circuits; that is the difference between "the
    model decided to search" and "a rule fired"."""
    tt.begin_turn()
    tt.record(tool="get_hours", success=True, latency_ms=1)
    with tt.trail_phase("agent"):
        tt.record(tool="search_kb", success=True, latency_ms=1)
    tt.record(tool="book_room", success=True, latency_ms=1)

    assert [r["agent"] for r in tt.collected()] == [
        "orchestrator", "agent", "orchestrator",
    ]


def test_the_phase_is_restored_even_if_the_block_raises():
    tt.begin_turn()
    try:
        with tt.trail_phase("agent"):
            raise RuntimeError("tool blew up")
    except RuntimeError:
        pass
    tt.record(tool="after", success=True, latency_ms=1)
    assert tt.collected()[0]["agent"] == "orchestrator"


def test_argument_values_are_never_recorded():
    """book_room carries a patron's name and email, and this trail is
    persisted and shown to library staff. Keys only."""
    tt.begin_turn()
    tt.record(
        tool="book_room",
        success=True,
        latency_ms=1,
        arg_keys={"patron_email": "sneaky", "room": "x"}.keys(),
    )
    row = tt.collected()[0]
    assert row["arg_keys"] == ["patron_email", "room"]
    assert "sneaky" not in repr(row)


def test_detail_is_truncated_so_one_row_cannot_carry_a_stack_trace():
    tt.begin_turn()
    tt.record(tool="t", success=False, latency_ms=1, detail="x" * 5000)
    assert len(tt.collected()[0]["detail"]) == 200


def test_a_runaway_turn_cannot_grow_without_bound():
    """A loop that dispatches forever must not turn into an unbounded
    insert batch on the socket handler."""
    tt.begin_turn()
    for i in range(tt._MAX_ROWS + 50):
        tt.record(tool=f"t{i}", success=True, latency_ms=1)
    assert len(tt.collected()) == tt._MAX_ROWS


def test_recording_never_raises_on_bad_input():
    """Telemetry must not be able to fail a served turn."""
    class Exploding:
        def __str__(self):
            raise ValueError("nope")

    tt.begin_turn()
    tt.record(tool=Exploding(), success=True, latency_ms=0)   # must not raise
    tt.record(tool="ok", success=True, latency_ms=0)
    assert [r["tool"] for r in tt.collected()] == ["ok"]


def test_an_explicit_agent_name_overrides_the_phase():
    tt.begin_turn()
    with tt.trail_phase("agent"):
        tt.record(tool="t", success=True, latency_ms=1, agent="slot_filling")
    assert tt.collected()[0]["agent"] == "slot_filling"
