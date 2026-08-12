"""
Abuse / cost guard for the public chat entry points (HTTP /ask and the
Socket.IO `message` event).

WHY: the bot is intentionally unauthenticated (a public library
assistant). With no auth, the only thing standing between a scripted
client and an unbounded OpenAI bill / DoS is input validation + rate
limiting -- and an audit (2026-05-18) confirmed there was NONE: a
single client could open many sockets, send arbitrarily large
messages, and spam turns, each one hitting `library_graph.ainvoke`
(real OpenAI spend). This directly threatens the (currently
exhausted) API budget, so it's the highest-value security item.

DESIGN -- deliberately dependency-free and in-process:
  * slowapi/fastapi-limiter need Redis and don't cover Socket.IO.
    The plan explicitly scopes this app to single-digit RPS with
    singleton clients, so a tiny in-memory sliding-window limiter is
    the right tool. (Multi-worker note: limits are PER WORKER. With
    one uvicorn worker that's exact; with N workers the effective
    limit is N x -- still a massive reduction vs. none. A shared
    Redis limiter is future work for horizontal scale, flagged not
    built.)
  * FAIL-OPEN: any internal error in the limiter must allow the
    request, never 500 the bot. A telemetry guard must not become an
    availability bug. (The opposite of the service guard, which
    fail-closes -- different risk: there, a wrong answer; here, a
    denied legitimate user.)

All limits are env-tunable with conservative defaults; a normal
library question is < 1 KB and a human sends a handful per minute.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from typing import Deque


def _int_env(name: str, default: int) -> int:
    try:
        v = int(os.getenv(name, "").strip() or default)
        return v if v > 0 else default
    except (ValueError, TypeError):
        return default


# A library question is short. 4000 chars is ~1000 tokens -- generous
# for any real question; longer is a paste-bomb / token-burn attempt.
MAX_MESSAGE_CHARS = _int_env("CHAT_MAX_MESSAGE_CHARS", 4000)
# Sliding window: at most MAX msgs per WINDOW seconds per client key.
RATE_MAX = _int_env("CHAT_RATE_MAX", 20)
RATE_WINDOW_S = _int_env("CHAT_RATE_WINDOW_S", 60)
# Hard ceiling on turns in one conversation -- stops a single
# conversation from being driven forever.
MAX_TURNS_PER_CONVERSATION = _int_env("CHAT_MAX_TURNS_PER_CONVERSATION", 80)

# --- the same limits, per source ADDRESS ----------------------------------
#
# RATE_MAX above is enforced per Socket.IO session id, which stops one person
# clicking fast in one tab and nothing else: a session id is per CONNECTION,
# so a script that opens a fresh socket for every message draws a fresh quota
# every time. Measured against production on 2026-08-12 -- 30 messages down
# 30 connections, 30 answered, zero throttled. The per-socket limit had no
# effect on the exact actor this module was written to stop.
#
# So the address gets its own budget. The ceiling is deliberately well above
# the per-socket one because Miami students share campus NAT egress: a limit
# tuned to one person would throttle a floor of King Library. 120/min needs
# roughly sixty simultaneously-active people behind one address before it
# bites, which a script passes in seconds and a beta cohort will not.
IP_RATE_MAX = _int_env("CHAT_IP_RATE_MAX", 120)

# Every accepted connection writes a Conversation row before a single message
# arrives, so connection floods cost database writes even when no message is
# ever sent. A real browser opens one socket and keeps it; thirty per minute
# is loose enough for a flapping phone network and tight enough to matter.
CONN_RATE_MAX = _int_env("CHAT_CONN_RATE_MAX", 30)


class SlidingWindowLimiter:
    """In-memory sliding-window counter. asyncio-single-threaded, so
    no lock needed. Keys are evicted lazily as they age out, so memory
    is bounded by the number of ACTIVE clients in the last window."""

    def __init__(self, max_events: int, window_s: int) -> None:
        self.max_events = max_events
        self.window_s = window_s
        self._hits: dict[str, Deque[float]] = defaultdict(deque)

    def allow(self, key: str, *, now: float | None = None,
              max_events: int | None = None) -> bool:
        """True if `key` is under the limit (and records the hit).
        False if it should be throttled.

        `max_events` overrides the construction-time ceiling for this call
        only. The budget guard uses it to tighten the limit without
        rebuilding the limiter, which would discard every client's window
        and hand a burst to whoever was already being throttled.
        """
        now = time.monotonic() if now is None else now
        cutoff = now - self.window_s
        q = self._hits[key]
        while q and q[0] < cutoff:
            q.popleft()
        ceiling = self.max_events if max_events is None else max_events
        if len(q) >= ceiling:
            if not q:                       # pragma: no cover - defensive
                del self._hits[key]
            return False
        q.append(now)
        return True

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)


# Module-level singletons -- one process-wide limiter per surface.
_chat_limiter = SlidingWindowLimiter(RATE_MAX, RATE_WINDOW_S)
_ip_limiter = SlidingWindowLimiter(IP_RATE_MAX, RATE_WINDOW_S)
_conn_limiter = SlidingWindowLimiter(CONN_RATE_MAX, RATE_WINDOW_S)

# How much more an address may send than a single socket. Derived rather than
# hardcoded so that lowering CHAT_RATE_MAX tightens BOTH limits together --
# otherwise an operator dropping the per-socket limit in an incident would
# leave the address ceiling untouched and wonder why nothing changed.
_IP_MULTIPLIER = max(1, IP_RATE_MAX // RATE_MAX)


class MessageRejected(Exception):
    """Raised by `validate_message` with a user-safe reason + the
    wire-appropriate code (HTTP status / socket error kind)."""

    def __init__(self, reason: str, *, code: int = 400) -> None:
        super().__init__(reason)
        self.reason = reason
        self.code = code


def validate_message(raw: object) -> str:
    """Coerce + bound a user message. Returns the cleaned string or
    raises MessageRejected. Does NOT trust type, size, or emptiness."""
    if not isinstance(raw, str):
        raise MessageRejected("Message must be text.", code=400)
    text = raw.strip()
    if not text:
        raise MessageRejected("Message is empty.", code=400)
    if len(text) > MAX_MESSAGE_CHARS:
        raise MessageRejected(
            f"Message too long ({len(text)} chars; limit "
            f"{MAX_MESSAGE_CHARS}). Please shorten your question.",
            code=413,
        )
    return text


def _budget_limits() -> tuple[int, int]:
    """(rate_max, max_turns) for right now, per the budget ladder.

    At level 3 the ceiling drops from 20/min to 6/min and the turn cap from
    80 to 20. A real student asks three to five questions and never notices;
    a script issuing 28,800 messages a day -- enough to spend the whole
    monthly budget in six hours -- does. Returns the normal limits if the
    budget state cannot be read (see budget.py: FAIL OPEN, LOUDLY).
    """
    try:
        from src.config.budget import current_state
        st = current_state()
        return st.rate_max, st.max_turns
    except Exception:  # noqa: BLE001 -- the limiter must never 500 the bot
        return RATE_MAX, MAX_TURNS_PER_CONVERSATION


def check_rate(client_key: str) -> None:
    """Raise MessageRejected(429) if `client_key` is over the rate.
    FAIL-OPEN: a limiter bug must not deny a legitimate user."""
    try:
        # The STRICTEST limit that applies, not "budget always wins": a
        # deliberately-lowered CHAT_RATE_MAX must keep its effect, and an
        # unreadable budget state must not silently RAISE the ceiling.
        budget_ceiling, _ = _budget_limits()
        ceiling = min(_chat_limiter.max_events, budget_ceiling)
        if not _chat_limiter.allow(client_key or "unknown",
                                   max_events=ceiling):
            raise MessageRejected(
                "You're sending messages too quickly. Please wait a "
                "few seconds and try again.",
                code=429,
            )
    except MessageRejected:
        raise
    except Exception:  # noqa: BLE001 -- never let the guard 500 the bot
        return


def check_ip_rate(ip: str) -> None:
    """Raise MessageRejected(429) if this ADDRESS is over its rate.

    Enforced in addition to check_rate, not instead of it: the two catch
    different actors. One socket over its limit is a person clicking; one
    address over its limit is either a script or a genuinely busy building,
    and the ceiling is set so that only the first reaches it.

    FAIL-OPEN, like everything else here.
    """
    try:
        if not ip or ip == "unknown":
            # An address we could not determine must not become a shared
            # bucket that throttles everyone at once.
            return
        budget_ceiling, _ = _budget_limits()
        ceiling = min(_ip_limiter.max_events, budget_ceiling * _IP_MULTIPLIER)
        if not _ip_limiter.allow(f"ip:{ip}", max_events=ceiling):
            raise MessageRejected(
                "You're sending messages too quickly. Please wait a "
                "few seconds and try again.",
                code=429,
            )
    except MessageRejected:
        raise
    except Exception:  # noqa: BLE001 -- never let the guard 500 the bot
        return


def connection_allowed(ip: str) -> bool:
    """False if this address is opening connections too fast.

    Checked before the connection is accepted, so a refused one costs no
    Conversation row. FAIL-OPEN: an error here admits the connection.
    """
    try:
        if not ip or ip == "unknown":
            return True
        return _conn_limiter.allow(f"conn:{ip}")
    except Exception:  # noqa: BLE001
        return True


def client_ip_from_environ(environ: dict) -> str:
    """Best-effort client IP for a Socket.IO connection.

    The socket handshake arrives as a WSGI-style environ, so the proxy
    headers are HTTP_-prefixed and upper-cased rather than the neat mapping
    an HTTP request object gives. nginx sets both X-Forwarded-For and
    X-Real-IP on the /smartchatbot/socket.io/ location (checked 2026-08-12);
    without them every client would look like 127.0.0.1 and share one bucket.

    Honours the FIRST hop of X-Forwarded-For, which is the client as seen by
    our own proxy. Never raises.
    """
    try:
        if not environ:
            return "unknown"
        xff = (environ.get("HTTP_X_FORWARDED_FOR") or "").strip()
        if xff:
            return xff.split(",")[0].strip() or "unknown"
        real = (environ.get("HTTP_X_REAL_IP") or "").strip()
        if real:
            return real
        return (environ.get("REMOTE_ADDR") or "").strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def conversation_turn_exceeded(turn_count: int) -> bool:
    """True if this conversation has hit the hard turn ceiling."""
    return turn_count >= _budget_limits()[1]


def client_ip_from_request(request) -> str:
    """Best-effort client IP for HTTP. The bot sits behind the Miami
    reverse proxy, so honor X-Forwarded-For's FIRST hop; fall back to
    the socket peer. Never raises."""
    try:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
        return getattr(getattr(request, "client", None), "host", "") or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


__all__ = [
    "CONN_RATE_MAX",
    "IP_RATE_MAX",
    "MAX_MESSAGE_CHARS",
    "MAX_TURNS_PER_CONVERSATION",
    "MessageRejected",
    "SlidingWindowLimiter",
    "check_ip_rate",
    "check_rate",
    "client_ip_from_environ",
    "client_ip_from_request",
    "connection_allowed",
    "conversation_turn_exceeded",
    "validate_message",
]
