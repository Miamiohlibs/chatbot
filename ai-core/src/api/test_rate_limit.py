"""
Offline tests for the chat abuse/cost guard.

Run: `python -m src.api.test_rate_limit` from ai-core/.

Pure, no API, no network. Deterministic time via the injected `now`.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_AI_CORE = _HERE.parent.parent
sys.path.insert(0, str(_AI_CORE))

from src.api import rate_limit as RL
from src.api.rate_limit import (
    MAX_MESSAGE_CHARS,
    MessageRejected,
    SlidingWindowLimiter,
    check_rate,
    client_ip_from_request,
    conversation_turn_exceeded,
    validate_message,
)


def test_validate_rejects_non_str() -> None:
    for bad in (None, 123, {"a": 1}, ["x"]):
        try:
            validate_message(bad)
            assert False, f"expected reject for {bad!r}"
        except MessageRejected as e:
            assert e.code == 400


def test_validate_rejects_empty() -> None:
    for bad in ("", "   ", "\n\t "):
        try:
            validate_message(bad)
            assert False
        except MessageRejected as e:
            assert e.code == 400


def test_validate_rejects_oversized_413() -> None:
    try:
        validate_message("x" * (MAX_MESSAGE_CHARS + 1))
        assert False
    except MessageRejected as e:
        assert e.code == 413


def test_validate_ok_strips() -> None:
    assert validate_message("  what are King hours?  ") == "what are King hours?"


def test_limiter_allows_then_blocks_then_slides() -> None:
    lim = SlidingWindowLimiter(max_events=3, window_s=60)
    t = 1000.0
    assert lim.allow("ip", now=t) is True
    assert lim.allow("ip", now=t + 1) is True
    assert lim.allow("ip", now=t + 2) is True
    # 4th within window -> blocked
    assert lim.allow("ip", now=t + 3) is False
    # after the window slides past the first 3 hits -> allowed again
    assert lim.allow("ip", now=t + 61) is True
    # a different key is independent
    assert lim.allow("other", now=t + 3) is True


def test_check_rate_raises_429_over_limit() -> None:
    # Swap in a tiny limiter so the test is deterministic + isolated.
    orig = RL._chat_limiter
    RL._chat_limiter = SlidingWindowLimiter(max_events=1, window_s=999)
    try:
        check_rate("k")  # 1st ok
        try:
            check_rate("k")  # 2nd -> over
            assert False, "expected 429"
        except MessageRejected as e:
            assert e.code == 429
    finally:
        RL._chat_limiter = orig


def test_check_rate_fails_open_on_internal_error() -> None:
    """A limiter bug must NOT deny a legitimate user (fail-open)."""
    orig = RL._chat_limiter

    class _Boom:
        def allow(self, *a, **k):
            raise RuntimeError("limiter exploded")

    RL._chat_limiter = _Boom()
    try:
        check_rate("k")  # must NOT raise
    finally:
        RL._chat_limiter = orig


def test_conversation_turn_ceiling() -> None:
    assert conversation_turn_exceeded(RL.MAX_TURNS_PER_CONVERSATION) is True
    assert conversation_turn_exceeded(RL.MAX_TURNS_PER_CONVERSATION - 1) is False


def test_client_ip_xff_and_fallback_and_safe() -> None:
    """This test used to assert the FIRST hop of X-Forwarded-For, which is the
    one value in the header a client writes itself. It was not testing a
    safeguard, it was pinning a bypass: reading it let one forged header buy a
    fresh rate-limit quota. Corrected 2026-08-12 after confirming against the
    running service that a forged 203.0.113.99 came back out unchanged.
    """
    class _R:
        def __init__(self, headers, host):
            self.headers = headers
            self.client = type("C", (), {"host": host})()

    # nginx appends the true peer, so the LAST hop is its own observation
    assert client_ip_from_request(
        _R({"x-forwarded-for": "203.0.113.7, 10.0.0.1"}, "10.0.0.1")
    ) == "10.0.0.1"
    assert client_ip_from_request(_R({}, "198.51.100.4")) == "198.51.100.4"
    # Garbage object -> never raises, returns 'unknown'
    assert client_ip_from_request(object()) == "unknown"


def main() -> int:
    tests = [
        test_validate_rejects_non_str,
        test_validate_rejects_empty,
        test_validate_rejects_oversized_413,
        test_validate_ok_strips,
        test_limiter_allows_then_blocks_then_slides,
        test_check_rate_raises_429_over_limit,
        test_check_rate_fails_open_on_internal_error,
        test_conversation_turn_ceiling,
        test_client_ip_xff_and_fallback_and_safe,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())


# --- budget-driven tightening (level 3) ----------------------------------
#
# At level 3 the ceiling drops from 20/min to 6/min and the turn cap from 80
# to 20. The reason is arithmetic, not policy: one client at 20/min can issue
# 28,800 messages a day, which on the expensive model is the entire monthly
# budget in about six hours (measured 2026-08-04).


def _state(tmp_path, level):
    from src.config import budget as B
    p = tmp_path / "state.json"
    B.write_state(B.BudgetState(level=level, month=__import__("datetime")
                                .date.today().strftime("%Y-%m")), p)
    return p


def test_limits_are_normal_at_level_zero(tmp_path, monkeypatch):
    from src.config import budget as B
    monkeypatch.setattr(B, "STATE_PATH", _state(tmp_path, B.L_NORMAL))
    B.reset_cache()
    assert RL._budget_limits() == (B.RATE_MAX_NORMAL, B.MAX_TURNS_NORMAL)
    assert RL.conversation_turn_exceeded(B.MAX_TURNS_NORMAL - 1) is False


def test_level_three_tightens_both_knobs(tmp_path, monkeypatch):
    from src.config import budget as B
    monkeypatch.setattr(B, "STATE_PATH", _state(tmp_path, B.L_TIGHTEN))
    B.reset_cache()
    assert RL._budget_limits() == (B.RATE_MAX_TIGHTENED, B.MAX_TURNS_TIGHTENED)
    # A conversation that was fine at 80 turns is now over the cap.
    assert RL.conversation_turn_exceeded(B.MAX_TURNS_TIGHTENED) is True
    assert RL.conversation_turn_exceeded(B.MAX_TURNS_TIGHTENED - 1) is False


def test_level_two_does_not_tighten_limits(tmp_path, monkeypatch):
    """Downgrading the model is NOT throttling. Conflating them would punish
    students at the first sign of a busy day."""
    from src.config import budget as B
    monkeypatch.setattr(B, "STATE_PATH", _state(tmp_path, B.L_CHEAP))
    B.reset_cache()
    assert RL._budget_limits() == (B.RATE_MAX_NORMAL, B.MAX_TURNS_NORMAL)


def test_the_strictest_limit_wins_not_the_budget(tmp_path, monkeypatch):
    """A deliberately-lowered CHAT_RATE_MAX must keep its effect even when
    the budget would allow more."""
    from src.config import budget as B
    monkeypatch.setattr(B, "STATE_PATH", _state(tmp_path, B.L_NORMAL))
    B.reset_cache()
    orig = RL._chat_limiter
    RL._chat_limiter = SlidingWindowLimiter(max_events=1, window_s=999)
    try:
        check_rate("k")
        try:
            check_rate("k")
            assert False, "a tighter local limiter must still throttle"
        except MessageRejected as e:
            assert e.code == 429
    finally:
        RL._chat_limiter = orig


def test_unreadable_budget_state_does_not_raise_the_ceiling(tmp_path, monkeypatch):
    """Failing open must mean "normal limits", never "no limits"."""
    from src.config import budget as B
    bad = tmp_path / "state.json"
    bad.write_text("{ not json")
    monkeypatch.setattr(B, "STATE_PATH", bad)
    B.reset_cache()
    rate, turns = RL._budget_limits()
    assert rate == B.RATE_MAX_NORMAL
    assert turns == B.MAX_TURNS_NORMAL


# --- who is a development client -----------------------------------------


def test_a_browser_is_a_student_and_a_test_harness_is_not():
    """A browser ALWAYS sends an Origin on a websocket handshake; curl,
    python-socketio and every test client do not."""
    from src.main import _looks_like_dev_client
    # real students
    for env in ({"HTTP_ORIGIN": "https://www.lib.miamioh.edu"},
                {"HTTP_ORIGIN": "https://new.lib.miamioh.edu"},
                {"HTTP_REFERER": "https://www.lib.miamioh.edu/use/"}):
        assert _looks_like_dev_client(env) is False, env
    # the operator's harness
    for env in ({}, {"HTTP_ORIGIN": ""},
                {"HTTP_ORIGIN": "http://localhost:8081"},
                {"HTTP_ORIGIN": "http://127.0.0.1:5173"}):
        assert _looks_like_dev_client(env) is True, env


# --- the bypass this module existed to stop, and did not ------------------
#
# Measured against production on 2026-08-12: 30 messages down 30 fresh
# connections were all answered and none throttled. The per-socket limit is
# real, but a session id is per CONNECTION, so reconnecting drew a fresh
# quota every time. These pin the address-keyed limits that close it.


def test_a_new_socket_does_not_reset_the_address_quota() -> None:
    """The attack, reduced: same address, a different session id each time."""
    RL._ip_limiter.reset("ip:10.0.0.7")
    blocked = 0
    for i in range(RL.IP_RATE_MAX + 10):
        try:
            # a brand-new session id on every single message
            RL.check_rate(f"ws:socket-{i}")
            RL.check_ip_rate("10.0.0.7")
        except MessageRejected:
            blocked += 1
    assert blocked >= 10, (
        f"reconnecting still bypassed the limit: only {blocked} of "
        f"{RL.IP_RATE_MAX + 10} were refused")
    RL._ip_limiter.reset("ip:10.0.0.7")


def test_two_students_behind_one_campus_nat_are_independent_of_a_script():
    """The cost of keying on address: shared egress. The ceiling has to sit
    above what a busy building does and below what a script does."""
    RL._ip_limiter.reset("ip:134.53.1.1")
    # Twenty people on one NAT address, five questions each, is normal use.
    for i in range(100):
        RL.check_ip_rate("134.53.1.1")     # must not raise
    RL._ip_limiter.reset("ip:134.53.1.1")


def test_an_unknown_address_is_not_one_shared_bucket() -> None:
    """If address extraction ever breaks, every client must not land in the
    same bucket and throttle each other."""
    for _ in range(RL.IP_RATE_MAX * 2):
        RL.check_ip_rate("")               # must not raise
        RL.check_ip_rate("unknown")        # must not raise


def test_connection_flood_is_refused_before_a_conversation_row() -> None:
    RL._conn_limiter.reset("conn:10.0.0.9")
    allowed = sum(1 for _ in range(RL.CONN_RATE_MAX + 20)
                  if RL.connection_allowed("10.0.0.9"))
    assert allowed == RL.CONN_RATE_MAX, (
        f"expected exactly {RL.CONN_RATE_MAX} connections to be admitted, "
        f"got {allowed}")
    RL._conn_limiter.reset("conn:10.0.0.9")


def test_the_socketio_handshake_environ_yields_the_real_client() -> None:
    """Behind nginx every socket's REMOTE_ADDR is 127.0.0.1, so reading the
    proxy headers is what makes the address limit mean anything at all."""
    assert RL.client_ip_from_environ(
        {"HTTP_X_REAL_IP": "134.53.4.9", "REMOTE_ADDR": "127.0.0.1"}) == "134.53.4.9"
    assert RL.client_ip_from_environ({"REMOTE_ADDR": "134.53.4.9"}) == "134.53.4.9"
    assert RL.client_ip_from_environ({}) == "unknown"
    assert RL.client_ip_from_environ(None) == "unknown"


def test_a_forged_x_forwarded_for_cannot_buy_a_fresh_quota() -> None:
    """The bug that made the address limit worthless for a day.

    nginx builds X-Forwarded-For as `<whatever the client claimed>, <true
    peer>`, so the FIRST hop is the client's own words. Reading it meant one
    header per request bought a new bucket -- no reconnecting required.
    Confirmed against the running service on 2026-08-12: a forged
    203.0.113.99 came straight back out as the derived address.
    """
    forged = "203.0.113.99"
    truth = "134.53.4.9"
    # what nginx actually produces when a client sends its own header
    env = {"HTTP_X_FORWARDED_FOR": f"{forged}, {truth}",
           "REMOTE_ADDR": "127.0.0.1"}
    got = RL.client_ip_from_environ(env)
    assert got != forged, "a client's own X-Forwarded-For must never be trusted"
    assert got == truth

    # X-Real-IP wins, because proxy_set_header REPLACES a forged one. Verified
    # through the real nginx path: a forged X-Real-IP came back as the peer.
    assert RL.client_ip_from_environ({
        "HTTP_X_REAL_IP": truth,
        "HTTP_X_FORWARDED_FOR": f"{forged}, {truth}",
    }) == truth

    # a long forged chain does not help either
    assert RL.client_ip_from_environ({
        "HTTP_X_FORWARDED_FOR": "1.1.1.1, 2.2.2.2, 3.3.3.3, " + truth,
    }) == truth


def test_the_http_helper_has_the_same_rule() -> None:
    """It has no callers, which is why it was worth fixing rather than leaving
    as a trap for the next HTTP entry point."""
    class _Req:
        def __init__(self, headers, host=None):
            self.headers = headers
            self.client = type("C", (), {"host": host})() if host else None

    assert RL.client_ip_from_request(
        _Req({"x-forwarded-for": "203.0.113.99, 134.53.4.9"})) == "134.53.4.9"
    assert RL.client_ip_from_request(
        _Req({"x-real-ip": "134.53.4.9",
              "x-forwarded-for": "203.0.113.99, 134.53.4.9"})) == "134.53.4.9"
    assert RL.client_ip_from_request(_Req({}, host="134.53.4.9")) == "134.53.4.9"
    assert RL.client_ip_from_request(_Req({})) == "unknown"


def test_tightening_the_socket_limit_tightens_the_address_limit_too() -> None:
    """An operator who drops CHAT_RATE_MAX during an incident must not find
    the address ceiling untouched."""
    assert RL._IP_MULTIPLIER >= 1
    assert RL.IP_RATE_MAX >= RL.RATE_MAX, (
        "the address ceiling must not be stricter than the per-socket one, "
        "or shared campus NAT throttles before a single tab does")
