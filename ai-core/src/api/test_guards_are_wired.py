"""Every abuse guard must be CALLED from the path that serves a student.

Three separate controls were found unwired on 2026-08-12, and each one had
config, documentation, and passing unit tests:

  * the rate limit was keyed on the socket id, so reconnecting reset it --
    30 messages down 30 connections, 30 answered, 0 throttled;
  * the address limit that replaced it read a header the client writes, so
    one forged X-Forwarded-For bought a fresh quota per request;
  * the per-conversation turn ceiling was never called at all --
    CHAT_MAX_TURNS_PER_CONVERSATION=80, tightened to 20 by the budget
    ladder, written into the state file, and measured at 85 turns served.

The common shape is not a broken function. Every one of those functions
worked perfectly in isolation. What was missing was the CALL, and no unit
test can see that, because a unit test invokes the function itself.

So this asserts the wiring. It parses the handler and looks for real call
nodes, which is deliberate: the first version of this test used a regex and
happily matched `# check_ip_rate(...)` in a comment -- it passed while the
guard was commented out. A test for missing wiring that cannot detect
missing wiring is worse than none, so the AST is what decides here.

If a guard legitimately moves, update REQUIRED_CALLS rather than deleting
the entry.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

_MAIN = Path(__file__).resolve().parents[1] / "main.py"

# The Socket.IO handler that runs for every student message.
HANDLER = "_v2_message"
CONNECT_HANDLER = "_v2_connect"

# guard -> why it exists, quoted back in the failure so the next person does
# not have to go digging before deciding what to do.
REQUIRED_IN_HANDLER = {
    "validate_message": "bounds message size; without it a paste-bomb is billed as tokens",
    "check_rate": "per-socket rate limit -- one person clicking fast",
    "check_ip_rate": "per-address rate limit -- the script; the ONLY one that "
                     "stops a client reconnecting for every message",
    "conversation_turn_exceeded": "per-conversation turn ceiling; unwired until "
                                  "2026-08-12, measured at 85 turns served",
    "is_paused": "the kill switch; checked first so a paused bot costs nothing",
}

REQUIRED_IN_CONNECT = {
    "connection_allowed": "connection flood -- each accepted socket writes a "
                          "Conversation row before any message arrives",
}


def _function(name: str, source: "str | None" = None) -> ast.AST:
    tree = ast.parse(source if source is not None
                     else _MAIN.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} not found -- the handler was renamed")


def _calls(fn: ast.AST) -> "dict[str, int]":
    """{called name: first line it is called on}. Real call nodes only."""
    out: "dict[str, int]" = {}
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        name = f.id if isinstance(f, ast.Name) else (
            f.attr if isinstance(f, ast.Attribute) else None)
        if name and name not in out:
            out[name] = node.lineno
    return out


def test_every_guard_is_called_in_the_message_handler() -> None:
    called = _calls(_function(HANDLER))
    missing = [f"  {n}() -- {why}" for n, why in REQUIRED_IN_HANDLER.items()
               if n not in called]
    assert not missing, (
        f"a guard exists but {HANDLER} never invokes it, which is how three "
        f"controls silently protected nobody:\n" + "\n".join(missing))


def test_the_connection_guard_is_called_when_a_socket_connects() -> None:
    called = _calls(_function(CONNECT_HANDLER))
    missing = [f"  {n}() -- {why}" for n, why in REQUIRED_IN_CONNECT.items()
               if n not in called]
    assert not missing, "\n".join(missing)


def test_the_kill_switch_comes_before_anything_expensive() -> None:
    """The operator's promise is that pausing takes the bot out of service
    immediately and cheaply -- no database write, no model call."""
    called = _calls(_function(HANDLER))
    for later in ("check_rate", "create_conversation"):
        if later in called:
            assert called["is_paused"] < called[later], (
                f"is_paused() is checked after {later}(), so a paused bot "
                f"still does work before refusing")


def test_the_turn_ceiling_comes_before_the_turn_is_served() -> None:
    """A ceiling enforced after the expensive part has happened is a log line,
    not a cost control."""
    called = _calls(_function(HANDLER))
    ceiling = called["conversation_turn_exceeded"]
    # Whichever of these the handler uses to actually run the turn. NOT
    # `to_thread`: the handler also uses it to fire the injection alert, and
    # matching that made this test fail against correct code -- an ordering
    # assertion is only worth having if it names the expensive call exactly.
    for runner in ("handle_v2_message", "run_turn_v2", "_run_turn_sync", "run_turn"):
        if runner in called:
            assert ceiling < called[runner], (
                f"the turn ceiling is checked after {runner}(), so refusing a "
                f"turn costs exactly as much as serving one")
            return
    raise AssertionError("could not find where the handler runs the turn -- "
                         "update the runner list")


def test_the_connection_guard_precedes_the_conversation_row() -> None:
    """A refused connection must not cost a database write; that is the whole
    reason the check sits in connect rather than in the message handler."""
    called = _calls(_function(CONNECT_HANDLER))
    if "create_conversation" in called:
        assert called["connection_allowed"] < called["create_conversation"], (
            "the connection is admitted and a Conversation row written before "
            "the flood check runs")


# --- proving THIS checker works -------------------------------------------
#
# The first version of this file used a regular expression and passed while
# check_ip_rate was commented out. A wiring test that cannot see missing
# wiring is worse than no test, because it is believed. These two pin the
# checker itself.


def test_a_commented_out_guard_does_not_count_as_wired() -> None:
    src = textwrap.dedent("""
        async def _v2_message(sid, text):
            # check_ip_rate(client_ips.get(sid, ""))
            return None
    """)
    assert "check_ip_rate" not in _calls(_function("_v2_message", src)), (
        "a call inside a comment was counted as a live call -- exactly the "
        "bug that let the regex version of this test pass while the guard "
        "was switched off")


def test_a_guard_named_only_in_a_string_does_not_count() -> None:
    src = textwrap.dedent("""
        async def _v2_message(sid, text):
            log("about to check_ip_rate(sid) shortly")
            return None
    """)
    assert "check_ip_rate" not in _calls(_function("_v2_message", src))


def test_the_ordering_check_detects_a_late_ceiling() -> None:
    src = textwrap.dedent("""
        async def _v2_message(sid, text):
            resp = await handle_v2_message(sid, text)
            if conversation_turn_exceeded(n):
                return None
            return resp
    """)
    called = _calls(_function("_v2_message", src))
    assert called["conversation_turn_exceeded"] > called["handle_v2_message"], (
        "the checker cannot tell a late ceiling from an early one")
