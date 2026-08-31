"""The staff-test link.

The point of this link is that it replaces a guess with a record. The tests
are therefore about what gets STORED, and about the ways a marker like this
goes wrong: sticking to somebody who has stopped testing, granting something
it should not, or breaking the front door when a client sends rubbish.
"""

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from src.api import staff_test as ST
from src.api.staff_test import (
    COOKIE,
    STAFF,
    build_staff_test_router,
    origin_from_cookie_header,
)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(build_staff_test_router())
    return TestClient(app, raise_server_exceptions=False)


# --- reading the marker ----------------------------------------------------


def test_the_marker_is_read_from_a_normal_cookie_header():
    assert origin_from_cookie_header(f"a=1; {COOKIE}={STAFF}; b=2") == STAFF


def test_no_marker_means_no_origin():
    assert origin_from_cookie_header("a=1; b=2") is None


@pytest.mark.parametrize("junk", [
    None, "", "=;;=", ";;;", "mu_chat_origin", "mu_chat_origin=",
    "mu_chat_origin=notstaff", "x" * 5000,
])
def test_rubbish_never_raises_inside_the_handshake(junk):
    # This runs on the socket handshake -- the front door for every patron.
    # A malformed header from a hostile client must not take it down.
    assert origin_from_cookie_header(junk) in (None, STAFF)


def test_a_similar_cookie_name_does_not_count():
    assert origin_from_cookie_header("mu_chat_origin_x=staff") is None
    assert origin_from_cookie_header("xmu_chat_origin=staff") is None


# --- the link itself -------------------------------------------------------


def test_the_link_is_under_a_prefix_nginx_actually_proxies(client):
    """A bare /staff-test 404'd in production.

    nginx proxies a fixed list of prefixes; anything else falls through to
    the static site. /librarian/ is on that list. This asserts the path so
    the route cannot drift back off it.
    """
    routes = [r.path for r in build_staff_test_router().routes]
    assert all(p.startswith("/librarian/") for p in routes), routes


def test_the_link_sets_the_marker_and_goes_straight_to_the_chat(client):
    """One click. It briefly showed a confirmation page with a
    three-second auto-continue, added because the bare redirect told the
    person nothing -- and the operator's answer was that the link was
    already three sections down a hub and an interstitial on top of that
    is another step in front of something that should be instant.

    What replaced it is better placed: the hub says whether this browser
    is marked, in a strip above everything else, readable without
    clicking at all.
    """
    r = client.get("/librarian/staff-test", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == ST.WIDGET_URL
    assert r.cookies.get(ST.COOKIE) == ST.STAFF


def test_the_link_grants_nothing(client):
    """It records which door somebody came through. It is not a login and
    must never be mistaken for one. The only cookie it may set is the
    marker, and the marker carries the literal string "staff"."""
    r = client.get("/librarian/staff-test", follow_redirects=False)
    assert r.cookies.get(ST.COOKIE) == ST.STAFF
    assert len(r.cookies) == 1
    assert not r.text.strip(), "a redirect, with no page to leak anything on"

def test_the_handshake_reads_the_cookie_and_passes_it_on():
    """Read from source. The handshake is expensive to import and the thing
    that can break is a wiring mistake, not a computation."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1] / "main.py").read_text()

    connect = src[src.index("async def _v2_connect("):]
    connect = connect[:connect.index("\nasync def ", 1)]

    assert "HTTP_COOKIE" in connect, (
        "the handshake does not look at the cookie header, so the staff "
        "marker can never reach a conversation")
    assert "origin_from_cookie_header" in connect
    assert "create_conversation(origin=origin)" in connect, (
        "the origin is read but not stored -- conversations will all come "
        "out unmarked, which is exactly how this shipped the first time")


def test_create_conversation_accepts_an_origin():
    import inspect

    from src.memory.conversation_store import create_conversation
    assert "origin" in inspect.signature(create_conversation).parameters


def test_ordinary_traffic_stores_no_origin_rather_than_a_made_up_one():
    """`origin` must stay NULL for normal visitors.

    Writing "web" for everyone else would look tidier and would be an
    assertion about traffic nobody measured -- the same mistake as calling
    an unlabelled conversation a patron.
    """
    import inspect

    from src.memory.conversation_store import create_conversation
    body = inspect.getsource(create_conversation)
    assert 'if origin:' in body, "origin should only be written when present"


# --- the state, said out loud --------------------------------------------

def test_turning_it_off_says_so_in_the_shared_look(client):
    r = client.get("/librarian/staff-test/off", follow_redirects=False)
    assert r.status_code == 200
    assert "no longer marked" in r.text
    assert "Miami University Libraries" in r.text, "staff page, not admin"


def test_the_hub_says_whether_this_browser_is_marked():
    """The reported problem, at the place somebody would look. The link
    set a cookie and dropped you on the chat; nothing anywhere told you
    it had taken."""
    from src.api.admin.hub_router import render_librarian_hub

    on = render_librarian_hub("CODE", marked=True)
    off = render_librarian_hub("CODE", marked=False)
    assert "is marked as staff testing" in on
    assert "Stop marking me" in on
    assert "not</b> marked" in off
    assert "Open in test mode" in off


def test_the_hub_offers_one_button_not_both():
    """Two buttons, one of which is always wrong for your current state,
    is how somebody turns the marking off believing they turned it on."""
    from src.api.admin.hub_router import render_librarian_hub

    on = render_librarian_hub("CODE", marked=True)
    assert "Open in test mode" not in on
    off = render_librarian_hub("CODE", marked=False)
    assert "Stop marking me" not in off


def test_the_hub_puts_the_switch_above_everything_else():
    """It was three sections down, under two paragraphs. Somebody who came
    to try the bot had to read past the report form to find the one
    control they need first. Reported 2026-08-31."""
    from src.api.admin.hub_router import render_librarian_hub

    off = render_librarian_hub("CODE", marked=False)
    assert off.index("Turn it on and open the chatbot") < off.index(
        "Report a wrong chatbot answer")
    on = render_librarian_hub("CODE", marked=True)
    assert on.index("Test mode is ON") < on.index("Report a wrong chatbot")
