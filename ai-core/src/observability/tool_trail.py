"""Per-turn tool-execution trail.

WHY THIS EXISTS
---------------
The admin review ticket has a "Tools called" table (see
`api/admin/review_view_router.py`) reading `ToolExecution` rows. Those
rows were never written for v2 traffic: `conversation_store.
log_tool_execution` had no callers outside the archived legacy
orchestrator, so every ticket rendered "Tools used: none" even on turns
that demonstrably hit search_kb, get_hours or LibCal.

This is the same v1->v2 seam that previously left ModelTokenUsage empty
(cost dashboards read $0) and Message.wasRefusal null (the review
queue's refusal filter matched 0 of 8,185 rows). Both were fixed by
threading the value out to the async socket handler and persisting it
there. This module is the collector for the third one.

DESIGN
------
`ToolRegistry.dispatch` is the single chokepoint every tool call passes
through -- the agent loop dispatches there, and so do the ~9
short-circuit paths in the orchestrator that call
`deps.tool_registry.dispatch(ToolCall(...))` directly.
`_SlotFillingRegistry.dispatch` delegates to the same method. Recording
there means no call site has to remember to opt in, and new tools are
covered automatically.

THREADING
---------
`run_turn` executes on an executor thread (see
`v2_serving.handle_v2_message`), and executor threads are REUSED across
turns. A ContextVar in a fresh thread starts empty, but a reused thread
keeps whatever the previous turn left behind, so `begin_turn()` must be
called at the top of every turn to reset the buffer. Concurrent turns
land on different threads and therefore get independent buffers.

Collection is deliberately best-effort: telemetry must never break a
served turn, so every public function swallows its own errors.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Iterable, Iterator, Optional

__all__ = [
    "begin_turn",
    "collected",
    "record",
    "trail_phase",
]

# `None` means "nobody is collecting" -- e.g. the eval harness or a unit
# test calling dispatch() directly. Recording is then a no-op rather
# than an error.
_TRAIL: contextvars.ContextVar[Optional[list[dict]]] = contextvars.ContextVar(
    "tool_trail", default=None
)

# Which stage of the turn is dispatching. The DB column is `agentName`;
# short-circuits are not the agent loop, and being able to tell them
# apart in the ticket is the whole point of recording them.
_PHASE: contextvars.ContextVar[str] = contextvars.ContextVar(
    "tool_trail_phase", default="orchestrator"
)

# One pathological turn must not turn into an unbounded insert batch.
_MAX_ROWS = 64


def begin_turn() -> None:
    """Start (or reset) collection for the current turn."""
    try:
        _TRAIL.set([])
        _PHASE.set("orchestrator")
    except Exception:  # pragma: no cover -- must never break a turn
        pass


@contextmanager
def trail_phase(name: str) -> Iterator[None]:
    """Label everything dispatched inside this block, then restore.

    Used by the agent loop so its calls are attributed to `agent`
    while the orchestrator's short-circuit dispatches stay
    `orchestrator`.
    """
    try:
        token = _PHASE.set(name)
    except Exception:  # pragma: no cover
        yield
        return
    try:
        yield
    finally:
        try:
            _PHASE.reset(token)
        except Exception:  # pragma: no cover
            pass


def record(
    *,
    tool: str,
    success: bool,
    latency_ms: int,
    arg_keys: Iterable[str] = (),
    detail: str = "",
    agent: Optional[str] = None,
) -> None:
    """Append one tool invocation to the current turn's trail.

    `arg_keys` is keys ONLY, never values: a book_room call carries a
    patron's name and email, and this trail is persisted for librarian
    review. Same rule the dispatch text log already follows.
    """
    try:
        trail = _TRAIL.get()
        if trail is None or len(trail) >= _MAX_ROWS:
            return
        trail.append(
            {
                "tool": str(tool),
                "agent": str(agent or _PHASE.get()),
                "success": bool(success),
                "latency_ms": int(latency_ms),
                "arg_keys": sorted({str(k) for k in (arg_keys or ())}),
                "detail": str(detail or "")[:200],
            }
        )
    except Exception:  # pragma: no cover -- must never break a turn
        pass


def collected() -> list[dict]:
    """Snapshot of this turn's trail, in dispatch order."""
    try:
        return list(_TRAIL.get() or [])
    except Exception:  # pragma: no cover
        return []


# `Conversation.toolUsed` is deliberately NOT written from here. It holds
# data for 1,549 pre-v2 conversations and the review page still falls back
# to it for those, but the ToolExecution rows are authoritative for
# anything new -- see api/admin/review_queries._tools_used_summary. Adding
# a denormalised second write per turn would cost a round trip on the
# serving path for a column nothing reads in preference to the rows.
