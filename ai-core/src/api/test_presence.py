"""The number somebody trusts a deploy to.

The dangerous failure here is not a crash, it is a count that is wrong in
the reassuring direction -- saying nobody is there when somebody is
mid-answer -- or wrong in the other one long enough that the operator
learns to ignore the page. Both are tested.
"""

import pytest

from src.api import presence


@pytest.fixture(autouse=True)
def clean():
    presence.reset_for_tests()
    yield
    presence.reset_for_tests()


# --- an open socket is not a person ---------------------------------------


def test_a_loaded_widget_is_not_somebody_a_restart_interrupts():
    """The widget connects when a library page LOADS. Counting those as
    people would make every afternoon look busy and the number useless."""
    for sid in ("a", "b", "c"):
        presence.connected(sid, now=0)
    s = presence.snapshot(now=1)
    assert s["open"] == 3
    assert s["in_conversation"] == 0
    assert s["waiting"] == 0
    assert s["safe_to_restart"]


def test_typing_is_what_makes_somebody_present():
    presence.connected("a", now=0)
    presence.message_received("a", now=10)
    s = presence.snapshot(now=20)
    assert s["in_conversation"] == 1
    assert not s["safe_to_restart"]


def test_a_conversation_goes_quiet_after_the_window():
    presence.connected("a", now=0)
    presence.message_received("a", now=10)
    late = 10 + presence.ACTIVE_WINDOW_S + 1
    assert presence.snapshot(now=late)["in_conversation"] == 0
    assert presence.snapshot(now=late)["safe_to_restart"]


# --- the one that actually costs somebody an answer ------------------------


def test_a_turn_in_flight_is_never_safe():
    presence.connected("a", now=0)
    presence.message_received("a", now=1)
    presence.turn_started("a", now=1)
    s = presence.snapshot(now=4)
    assert s["waiting"] == 1
    assert s["longest_wait_s"] == 3.0
    assert not s["safe_to_restart"]
    assert "loses the question" in s["verdict"]


def test_waiting_outranks_being_in_a_conversation_in_the_verdict():
    """Two people, two different costs. The verdict has to name the one
    that loses an answer, not the one that loses a thread."""
    presence.connected("a", now=0)
    presence.connected("b", now=0)
    presence.message_received("a", now=1)
    presence.message_received("b", now=1)
    presence.turn_started("b", now=1)
    assert "waiting on an answer" in presence.snapshot(now=2)["verdict"]


def test_a_finished_turn_stops_counting_immediately():
    presence.connected("a", now=0)
    presence.turn_started("a", now=1)
    presence.turn_finished("a")
    assert presence.snapshot(now=2)["waiting"] == 0


def test_a_wedged_turn_expires_rather_than_blocking_deploys_for_ever():
    """A crashed turn that never called turn_finished would otherwise pin
    "do not restart" on the page permanently, and a warning that is always
    on is one nobody reads."""
    presence.connected("a", now=0)
    presence.turn_started("a", now=0)
    assert presence.snapshot(now=presence.MAX_TURN_S + 1)["waiting"] == 0


# --- leaks ----------------------------------------------------------------


def test_disconnecting_clears_everything_about_that_socket():
    presence.connected("a", now=0)
    presence.message_received("a", now=1)
    presence.turn_started("a", now=1)
    presence.disconnected("a")
    s = presence.snapshot(now=2)
    assert (s["open"], s["in_conversation"], s["waiting"]) == (0, 0, 0)


def test_a_missed_disconnect_does_not_inflate_the_count_for_ever():
    """An inflated count is the failure that makes somebody stop believing
    the page, so the snapshot prunes anything whose socket is gone."""
    presence.connected("a", now=0)
    presence.message_received("a", now=1)
    presence.turn_started("a", now=1)
    presence._open.pop("a")          # the disconnect handler never ran
    s = presence.snapshot(now=2)
    assert (s["in_conversation"], s["waiting"]) == (0, 0)
    assert not presence._last_message and not presence._in_flight


def test_a_message_from_a_socket_we_never_saw_open_is_ignored():
    presence.message_received("ghost", now=1)
    assert presence.snapshot(now=2)["in_conversation"] == 0


# --- the card -------------------------------------------------------------


def test_the_card_leads_with_the_answer_not_the_arithmetic():
    from src.api.admin.presence_view import render_card

    presence.connected("a", now=0)
    presence.turn_started("a", now=0)
    body = render_card(presence.snapshot(now=1))
    assert body.index("waiting on an answer") < body.index("widget loaded")
    assert "class='warn'" in body


def test_the_card_is_calm_when_nobody_is_there():
    from src.api.admin.presence_view import render_card

    assert "class='good'" in render_card(presence.snapshot(now=1))


def test_the_card_says_what_in_a_conversation_means():
    """A number whose definition is elsewhere is a number people invent a
    definition for."""
    from src.api.admin.presence_view import render_card

    assert "typed something in the last" in render_card()


def test_the_json_gives_a_script_something_to_branch_on():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.admin.presence_view import build_presence_router

    app = FastAPI()
    app.include_router(build_presence_router({}))
    got = TestClient(app).get("/admin/presence.json").json()
    assert got["safe_to_restart"] is True
    presence.connected("a")
    presence.turn_started("a")
    assert TestClient(app).get(
        "/admin/presence.json").json()["safe_to_restart"] is False
