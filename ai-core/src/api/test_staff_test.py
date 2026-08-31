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


def test_the_link_sets_the_marker_and_says_so(client):
    """It used to be a bare 302 straight onto the chat. That worked and
    told the person nothing, so the only way to find out whether the click
    had taken was to hold a conversation and go looking for it -- and a
    conversation you never typed into does not appear in the console at
    all, which reads exactly like a broken link. Reported 2026-08-31."""
    r = client.get("/librarian/staff-test", follow_redirects=False)
    assert r.status_code == 200
    assert "marked as staff testing" in r.text
    # The marker is what actually matters, and it is set either way.
    assert r.cookies.get(ST.COOKIE) == ST.STAFF
    # ...and it still hands them to the widget without a second thought.
    assert ST.WIDGET_URL in r.text
    assert f"url={ST.WIDGET_URL}" in r.text, "no auto-continue"

def test_the_marker_dies_with_the_browser(client):
    # A session cookie. A librarian who tests today and works the desk
    # tomorrow must not still be labelled -- that would relabel real work as
    # a test, which is the failure this whole feature exists to prevent.
    raw = client.get("/librarian/staff-test", follow_redirects=False).headers["set-cookie"]
    low = raw.lower()
    assert "max-age" not in low and "expires" not in low


def test_the_marker_is_not_readable_by_page_scripts(client):
    raw = client.get("/librarian/staff-test", follow_redirects=False).headers["set-cookie"]
    assert "httponly" in raw.lower()


def test_turning_it_off_clears_the_marker(client):
    client.get("/librarian/staff-test", follow_redirects=False)
    r = client.get("/librarian/staff-test/off")
    assert r.status_code == 200
    assert "no longer marked" in r.text
    set_cookie = r.headers.get("set-cookie", "").lower()
    assert COOKIE in set_cookie
    assert 'max-age=0' in set_cookie or 'expires=thu, 01 jan 1970' in set_cookie


def test_the_status_endpoint_reports_the_current_state(client):
    assert client.get("/librarian/staff-test/status").json() == {"staff_test": False}
    client.get("/librarian/staff-test", follow_redirects=False)
    assert client.get("/librarian/staff-test/status").json() == {"staff_test": True}


def test_the_link_grants_nothing(client):
    """It records which door somebody came through. It is not a login and
    must never be mistaken for one.

    Written against what a leak would actually LOOK like rather than
    against the words. Scanning for the bare word "admin" caught the
    stylesheet's own comments and the page title, which is how this test
    spent a while failing on a page that leaked nothing -- and it did
    find one real thing: staff pages were titled "Smart Chatbot admin".
    """
    r = client.get("/librarian/staff-test", follow_redirects=False)
    body = r.text
    assert "key=" not in body, "no admin key in a staff-facing page"
    assert "type='password'" not in body and 'type="password"' not in body
    assert "/admin/" not in body, "no door into the operator console"
    assert "Smart Chatbot admin" not in body, "this is not the admin console"
    # The only cookie it may set is the marker, and the marker is not a
    # credential: it carries the literal string "staff" and nothing else.
    assert r.cookies.get(ST.COOKIE) == ST.STAFF
    assert len(r.cookies) == 1

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
