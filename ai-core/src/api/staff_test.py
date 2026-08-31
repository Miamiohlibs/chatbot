"""The link library staff use when they are TRYING the bot, not using it.

THE PROBLEM THIS SOLVES
    Nothing distinguished a librarian testing from a patron asking. Both
    arrive in the same browser, over the same socket, and the system stores
    no identity by design. Telling them apart meant reading transcripts and
    guessing -- 36 questions in 39 minutes is plainly somebody working
    through a list, but "plainly" is not evidence, and the beta report had
    to revise its "real users" count three times because every guess leaned
    the same way.

    A guess that leans towards "patron" overstates real usage. That is the
    expensive direction to be wrong in: it is the number leadership reads.

WHY IT LIVES UNDER /librarian/
    nginx proxies a fixed list of prefixes to this app; a bare /staff-test
    landed on the static site and 404'd, which is how the first version of
    this shipped. /librarian/ is already proxied and is already where staff
    go, so the link needs no infrastructure change and sits where the people
    who use it are looking.

HOW IT WORKS
    Staff open /librarian/staff-test instead of the normal page. That sets a session
    cookie and redirects to the ordinary widget -- same bot, same answers,
    nothing about the experience changes. Every conversation opened while
    the cookie is present is stored with origin="staff".

    A cookie rather than a URL parameter because it survives the reload and
    the in-app navigation that a query string does not, and because it needs
    no frontend change at all: the socket handshake already receives the
    request headers.

    It is a SESSION cookie. It dies with the browser, so a librarian who
    tests today and helps a patron at the desk tomorrow is not still marked.
    /staff-test/off clears it immediately for anyone who wants that sooner.

WHAT IT IS NOT
    Not authentication, and not a claim about who someone is. It records
    which door they came through, which is a fact, and leaves everything
    else alone.
"""

from __future__ import annotations

import logging

# Module level. `from __future__ import annotations` above makes every
# annotation a string and FastAPI resolves them against MODULE globals, so a
# Request imported inside the factory is invisible and the parameter is read
# as a request body -- a 422 on a route that is supposed to just answer a
# question. Three other routers shipped that bug on 2026-08-21.
try:  # pragma: no cover - FastAPI is always present in production
    from fastapi import Request
except ImportError:  # pragma: no cover
    Request = object  # type: ignore[assignment,misc]

logging.getLogger(__name__)

COOKIE = "mu_chat_origin"
STAFF = "staff"
WIDGET_URL = "/smartchatbot/"


def origin_from_cookie_header(cookie_header: str | None) -> str | None:
    """"staff" if this request carries the staff marker, else None.

    Parsed by hand rather than with http.cookies because a malformed header
    from a hostile client must not raise inside the socket handshake -- the
    handshake is the front door for every patron.
    """
    if not cookie_header:
        return None
    for part in str(cookie_header).split(";"):
        name, _, value = part.strip().partition("=")
        if name.strip() == COOKIE and value.strip() == STAFF:
            return STAFF
    return None


def build_staff_test_router():
    from fastapi import APIRouter, Response  # type: ignore
    from fastapi.responses import HTMLResponse, RedirectResponse  # type: ignore

    router = APIRouter(tags=["ops"])

    @router.get("/librarian/staff-test")
    async def staff_test() -> Response:
        """Set the marker and go. One click, straight to the chat.

        This briefly showed a confirmation page with a three-second
        auto-continue, added on 2026-08-31 because the bare redirect told
        the person nothing. The operator's answer the same day: the link
        was already buried three sections down a hub, and an interstitial
        on top of that is another step in front of a thing that should be
        instant.

        What replaces it is better placed anyway -- the hub says whether
        this browser is marked, in a strip at the very top, before
        anything else on the page. The state is readable without clicking
        at all, which the confirmation never was.
        """
        resp = RedirectResponse(WIDGET_URL, status_code=302)
        resp.set_cookie(
            COOKIE, STAFF,
            path="/",
            httponly=True,
            samesite="lax",
            # No max-age: a session cookie, gone when the browser closes.
            # A marker that outlives the testing session would quietly
            # relabel real desk work as a test.
        )
        return resp

    @router.get("/librarian/staff-test/off")
    async def staff_test_off() -> Response:
        from src.api.admin import admin_ui as ui

        resp = HTMLResponse(ui.page(
            "Test mode off",
            "<h1>Staff test mode is off</h1>"
            "<p class='lede'>Conversations from this browser are no longer "
            "marked as staff testing. From now on they count the same way a "
            "student's question does.</p>"
            f"<div class='acts'>{ui.action(WIDGET_URL, 'Open the chatbot')}"
            f"{ui.action('/librarian/staff-test', 'Turn it back on', ghost=True)}"
            "</div>",
            chrome=False))
        resp.delete_cookie(COOKIE, path="/")
        return resp

    @router.get("/librarian/staff-test/status")
    async def staff_test_status(request: Request) -> dict:
        return {"staff_test": origin_from_cookie_header(
            request.headers.get("cookie")) == STAFF}

    return router


__all__ = ["COOKIE", "STAFF", "build_staff_test_router",
           "origin_from_cookie_header"]
