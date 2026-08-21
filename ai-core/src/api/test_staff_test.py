"""The staff-test link.

The point of this link is that it replaces a guess with a record. The tests
are therefore about what gets STORED, and about the ways a marker like this
goes wrong: sticking to somebody who has stopped testing, granting something
it should not, or breaking the front door when a client sends rubbish.
"""

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

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


def test_the_link_sets_the_marker_and_lands_on_the_ordinary_widget(client):
    r = client.get("/librarian/staff-test", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/smartchatbot/"
    assert r.cookies.get(COOKIE) == STAFF


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
    # It records which door somebody came through. It is not a login, and
    # must never be mistaken for one.
    r = client.get("/librarian/staff-test", follow_redirects=False)
    body = r.text.lower()
    for word in ("token", "admin", "key=", "password"):
        assert word not in body


# --- the handshake wiring --------------------------------------------------
#
# The route setting a cookie and the dashboard reading `origin` were both
# tested, and the link between them -- the socket handshake -- was not. That
# is where the first version failed: everything worked except that nothing
# ever wrote the value.


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
