"""Who is using the bot right now, for the minute before a restart.

WHY THIS EXISTS
    Operator, 2026-08-30: "这样我每次推新的commit的时候不至于把当前在线的
    学生给挤掉". Deploying restarts the service, and until now the only way
    to know whether that was about to land on somebody was to guess from
    the hour.

WHAT A RESTART ACTUALLY COSTS, WHICH IS WHY THERE ARE THREE NUMBERS
    A single count of open sockets would be the easy thing to show and it
    would be misleading, because most open sockets are nobody. The widget
    opens its connection when a library page LOADS, so every person with a
    library tab open in the background is in that number and none of them
    would notice a restart: socket.io reconnects on its own and they had
    no conversation to lose.

    The three that differ:

      open              A browser has the widget loaded. Loses nothing.
      in_conversation   Somebody has typed in the last few minutes. A
                        restart drops the socket, and _v2_connect issues a
                        NEW conversation on reconnect -- so their thread is
                        gone and the bot is unreachable for the warm-up.
      waiting           A turn is being computed for them right now. The
                        question is lost with nothing shown. This is the
                        one that is actually rude.

    The verdict is written from `waiting` first and `in_conversation`
    second, because those are the two that cost a person something.

ONE PROCESS
    These are in-memory counts for THIS worker. `chatbot.service` runs
    uvicorn with no `--workers`, so there is exactly one and the number is
    the whole truth. Adding workers later would silently make it a
    fraction, which is worse than not having it -- if that day comes this
    has to move to Redis or the socket.io manager, not stay as it is.
"""

from __future__ import annotations

import time
from typing import Optional

# How long after somebody's last message they still count as being in a
# conversation. Long enough to cover reading an answer and typing a
# follow-up; short enough that a tab left open for an hour is not counted
# as a person waiting.
ACTIVE_WINDOW_S = 300

# How long a turn may plausibly be in flight before it is treated as
# abandoned rather than pending. Without this a crashed turn wedges
# `waiting` at 1 for ever, the page says "do not restart" permanently, and
# the operator learns to ignore it -- which is worse than showing nothing.
MAX_TURN_S = 180

# What a restart costs the people counted above. Measured on the t4g.medium
# 2026-08-12: cold start to first answer.
WARM_UP_S = 60

_open: dict = {}          # sid -> monotonic time the socket opened
_last_message: dict = {}  # sid -> monotonic time of their last question
_in_flight: dict = {}     # sid -> monotonic time the current turn started


def _now(now: Optional[float] = None) -> float:
    # monotonic, not wall time: every number here is a duration, and an
    # NTP correction must not make somebody look like they have been
    # waiting since yesterday.
    return time.monotonic() if now is None else now


def connected(sid: str, *, now: Optional[float] = None) -> None:
    _open[sid] = _now(now)


def disconnected(sid: str) -> None:
    _open.pop(sid, None)
    _last_message.pop(sid, None)
    _in_flight.pop(sid, None)


def message_received(sid: str, *, now: Optional[float] = None) -> None:
    _last_message[sid] = _now(now)


def turn_started(sid: str, *, now: Optional[float] = None) -> None:
    _in_flight[sid] = _now(now)


def turn_finished(sid: str) -> None:
    _in_flight.pop(sid, None)


def reset_for_tests() -> None:
    _open.clear()
    _last_message.clear()
    _in_flight.clear()


def snapshot(*, now: Optional[float] = None) -> dict:
    """The three counts, and what they mean for restarting.

    Also prunes: a socket whose disconnect was missed would otherwise sit
    in these dicts for the life of the process, and an inflated count is
    the failure mode that makes the operator stop believing the page.
    """
    t = _now(now)

    for sid in list(_last_message):
        if sid not in _open:
            _last_message.pop(sid, None)
    for sid, started in list(_in_flight.items()):
        if sid not in _open or (t - started) > MAX_TURN_S:
            _in_flight.pop(sid, None)

    waits = [t - started for started in _in_flight.values()]
    in_conversation = sum(
        1 for sid, last in _last_message.items()
        if sid in _open and (t - last) <= ACTIVE_WINDOW_S
    )
    waiting = len(waits)
    open_now = len(_open)

    if waiting:
        safe = False
        verdict = (
            f"{waiting} waiting on an answer right now. Restarting loses "
            f"the question with nothing shown to them — give it a few "
            f"seconds."
        )
    elif in_conversation:
        safe = False
        verdict = (
            f"{in_conversation} in the middle of a conversation. A restart "
            f"ends their thread and the bot cannot answer for about "
            f"{WARM_UP_S} seconds."
        )
    elif open_now:
        safe = True
        verdict = (
            f"Nobody is mid-conversation. {open_now} browser(s) have the "
            f"widget loaded and will reconnect on their own — they have "
            f"nothing to lose."
        )
    else:
        safe = True
        verdict = "Nobody is connected. Deploy away."

    return {
        "open": open_now,
        "in_conversation": in_conversation,
        "waiting": waiting,
        "longest_wait_s": round(max(waits), 1) if waits else 0.0,
        "safe_to_restart": safe,
        "verdict": verdict,
        "warm_up_s": WARM_UP_S,
        "active_window_s": ACTIVE_WINDOW_S,
    }
