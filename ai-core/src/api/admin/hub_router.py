"""
One-bookmark landing pages for the operator and for library staff.

Operator request 2026-07-17: "I can't remember all these URLs -- give me
one dashboard with links." Two audiences, two gates:

  GET /admin/          -- operator hub (ADMIN_API_TOKEN). Links to every
                          admin surface with the token already carried in
                          the query string, plus the shareable librarian
                          form link and the public probes.
  GET /librarian/      -- staff hub (LIBRARIAN_TICKET_CODE). The report
                          form plus a plain account of what happens after
                          they send it; new staff surfaces get added here
                          so staff only ever bookmark one URL.

Same zero-dependency server-rendered HTML approach as the other admin
views; the only interpolated secrets are the ones the visitor already
presented (their own key).
"""

from __future__ import annotations

from typing import Any, Optional

try:
    from starlette.requests import Request  # type: ignore
except Exception:  # noqa: BLE001
    Request = Any  # type: ignore


from src.api.admin import admin_ui as ui


def _card(title: str, desc: str, actions: str, *, on: bool = False) -> str:
    return (f"<div class='card{' on' if on else ''}'>"
            f"<div class='q'>{ui.e(title)}</div>"
            f"<div><small class='dim'>{ui.e(desc)}</small></div>"
            f"<div class='acts'>{actions}</div></div>")


def _section(heading: str, blurb: str, cards: str) -> str:
    return (f"<h2>{ui.e(heading)}</h2>"
            f"<p class='sub'>{ui.e(blurb)}</p>{cards}")


def render_admin_hub(admin_key: str, librarian_code: str, caller=None,
                     counts: "Optional[dict]" = None,
                     presence_snapshot: "Optional[dict]" = None) -> str:
    """The operator dashboard.

    Rebuilt 2026-07-28: it used to be a flat list of card links, so the
    only way to answer "is there anything waiting for me?" was to open
    every page. Now the counts lead, colored by whether they need
    action, and the links live under them.

    Regrouped 2026-08-08, on the operator's report that the categories
    did not read clearly. Two things were wrong. The cards sat in one
    bucket called "Tools" that mixed working a queue, changing what the
    bot says, and watching it run -- three different jobs. And the stop
    button (/admin/service) had no link anywhere in the UI, so taking
    the bot out of service meant knowing the URL by heart. Sections are
    now named for the job, and service state leads the page.
    """
    from src.api.admin.killswitch_router import is_paused, pause_reason

    c = counts or {}
    k = f"?key={ui.e(admin_key)}"
    tickets = int(c.get("tickets") or 0)
    flagged = int(c.get("flagged") or 0)
    praised = int(c.get("praised") or 0)
    corrections = int(c.get("corrections") or 0)

    down = is_paused()
    banner = ""
    if down:
        banner = (
            "<div class='banner down'>"
            "<b>The bot is OUT OF SERVICE.</b>"
            "<div><small>Every question is being answered with a "
            "maintenance notice pointing patrons at Ask Us.</small></div>"
            f"<div class='acts'>{ui.action(f'/admin/service{k}', 'Put it back in service', primary=True)}</div>"
            f"<div style='margin-top:.5rem'><code>{ui.e(pause_reason())}</code></div>"
            "</div>"
        )

    stats = (
        ui.stat_card(f"/admin/tickets/view{k}", tickets,
                     "staff tickets to work", needs=tickets > 0)
        + ui.stat_card(f"/admin/conversations{k}{'&' if k else '?'}needs=1",
                       flagged, "flagged turns to review", needs=flagged > 0)
        + ui.stat_card(
            f"/admin/conversations{k}{'&' if k else '?'}flag=thumbs_up",
            praised, "thumbs-up to skim")
        + ui.stat_card(f"/admin/corrections/view{k}", corrections,
                       "corrections live now")
    )
    # TWO DIFFERENT THINGS, NOT ONE SUM.
    #
    # This added tickets to flagged turns and called the total "items
    # waiting on you". A ticket is a colleague asking for something. A
    # flagged turn is a turn that MIGHT have gone badly -- and on
    # 2026-08-31 the queue held 326 of them, of which 313 were our own
    # replays and staff testing. The biggest, reddest number on the
    # console was 96% not-work, and it said it was waiting on you.
    #
    # Said separately, so neither borrows the other's urgency.
    def _n(n: int, one: str, many: str) -> str:
        return f"{n} {one if n == 1 else many}"

    if not tickets and not flagged:
        headline = "Nothing needs you right now."
    elif tickets and flagged:
        headline = (f"{_n(tickets, 'ticket', 'tickets')} to work, and "
                    f"{_n(flagged, 'flagged turn', 'flagged turns')} to look "
                    f"through.")
    elif tickets:
        headline = f"{_n(tickets, 'ticket', 'tickets')} to work."
    else:
        headline = (f"No tickets waiting. "
                    f"{_n(flagged, 'flagged turn', 'flagged turns')} to look "
                    f"through.")

    # The queue is mostly ours, and the way out of that is one click. No
    # number here on purpose -- knowing the split costs a 2,000-row read
    # and a classification pass, which is not a thing to do on every
    # dashboard load. The sweep says the real figure because it does the
    # real query. Shown only while the queue is big enough for it to be
    # true; after a sweep it is around thirty and this would be noise.
    sweep_hint = ""
    if flagged >= 50:
        sweep_hint = (
            f"<p class='hint' style='margin:-.9rem 0 1.4rem'>Most of that "
            f"queue is our own testing rather than a patron's bad "
            f"experience. <a href='/admin/review/close-testing{k}'>See how "
            f"many, and close them</a> — reversible, nothing is deleted."
            f"</p>")

    # 0. What actually happened. Reading the day's traffic is the most
    #    frequent thing an operator does and used to be the hardest: it
    #    meant Flagged -> the `all` preset -> scrolling a mixed feed.
    reading = _section(
        "What people asked",
        "Start here to see the day, not just the problems.",
        _card("Conversations by day",
              "Every conversation for one day, newest first, with the "
              "turns worth opening marked. Oxford time.",
              ui.action(f"/admin/conversations{k}", "Today", primary=True))
        + _card("Search",
                "One word across every conversation held — what patrons "
                "typed, what the bot said, or both. Browsing a day at a "
                "time was the only way to find anything before.",
                ui.action(f"/admin/search{k}", "Open")),
    )

    # 1. The path a wrong answer travels: someone reports it -> you read
    #    the turn -> you change what the bot says. Same order on screen.
    wrong = _section(
        "When an answer is wrong",
        "Report comes in, you read the turn, you change what the bot says.",
        _card("Correction tickets",
              "Staff reports of wrong answers. Work them open → in "
              "progress → done; each links to the corrections tool.",
              ui.action(f"/admin/tickets/view{k}", "Open",
                        primary=tickets > 0))
        + _card("What went wrong",
                "Refusals, thumbs-down and low-confidence turns across a "
                "date range, with the patron's rating and what the bot "
                "classified the question as.",
                ui.action(f"/admin/conversations{k}"
                          f"{'&' if k else '?'}needs=1",
                          "Open", primary=flagged > 0))
        + _card("Manual corrections",
                "Suppress, replace, pin or blacklist a source. Takes "
                "effect on the next message — no deploy.",
                ui.action(f"/admin/corrections/view{k}", "Open")),
    )

    # 2. Everything about whether it is up and what it costs.
    running = _section(
        "Keep it running",
        "Is it up, what is it spending, and how to stop it.",
        _card("Service control",
              "The stop button. The bot keeps answering — with a "
              "maintenance notice — so the widget never shows a broken "
              "page. Survives a restart; recovery is one click."
              if not down else
              "The bot is out of service right now. Put it back here.",
              ui.action(f"/admin/service{k}",
                        "Put the bot back in service" if down
                        else "Take the bot out of service", primary=down))
        + _card("Cost dashboard",
                "Daily LLM spend by model and call site (nightly rollup).",
                ui.action(f"/admin/cost{k}", "Open"))
        + _card("Health checks",
                "Probes are public (no key) so an external monitor can "
                "poll them.",
                ui.action("/health/ready", "Dependency probes")
                + ui.action("/smoketest", "End-to-end smoke test")),
    )

    staff_link = (
        f"/librarian/?key={ui.e(librarian_code)}" if librarian_code else ""
    )
    staff = (
        "<h2>Share with library staff</h2>"
        + (f"<div class='card'><div class='q'>Staff hub</div>"
           f"<div><small class='dim'>Send library staff THIS link — it "
           f"carries their access code and shows no admin surfaces.</small>"
           f"</div><div class='acts'>"
           f"{ui.action(staff_link, 'Open staff hub')}</div>"
           f"<div style='margin-top:.5rem'><code>{ui.e(staff_link)}</code>"
           f"</div></div>"
           if staff_link else
           "<div class='note'>LIBRARIAN_TICKET_CODE is not set — the "
           "staff form is closed.</div>")
    )

    # High on the page, under the service banner. The question it answers
    # -- "am I about to land a deploy on somebody?" -- is asked at the
    # moment of arriving here, not after reading four cards.
    from src.api.admin.presence_view import render_card

    live = presence_snapshot or _live()
    now_card = render_card(live, key=admin_key)

    body = (
        f"{banner}<h1>Dashboard</h1><p class='lede'>{ui.e(headline)}</p>"
        f"<div class='stats'>{stats}</div>"
        f"{sweep_hint}"
        f"{now_card}"
        f"{reading}{wrong}{running}{staff}"
        f"<p><small class='dim'>Bookmark this page — every link carries "
        f"your key.</small></p>"
    )
    # Refresh only while somebody is actually there. A dashboard that
    # reloads every fifteen seconds around the clock is one that fights
    # the reader; one that never reloads is one whose live number is a
    # screenshot from whenever they opened the tab.
    return ui.page("Dashboard", body, current="/admin/", key=admin_key,
                   who=caller, counts=counts,
                   refresh_s=15 if live["open"] else 0)


def _live() -> dict:
    from src.api import presence

    return presence.snapshot()


def render_librarian_hub(code: str, caller=None,
                         marked: bool = False) -> str:
    """Staff hub. Deliberately has NO operator nav or counts.

    THREE THINGS, ONE SCREEN.
        Operator, 2026-09-01: "字太多了 即使是图书馆员也需要读很多东西 太累".
        It ran to five sections and about two hundred and fifty words for
        three actions, and said whether test mode was on TWICE -- once in
        a strip at the top and again inside the card below it.

        A department head opens this to read what patrons asked, to say
        an answer was wrong, or to mark their browser before trying the
        bot. That is three cards with a line each.

    Reading comes first because it is what the other two follow from: you
    notice a bad answer by reading one, and you mark your browser before
    going to look for one.
    """
    k = f"?key={ui.e(code)}" if code else ""

    # WHO SEES THE TRANSCRIPTS, AND WHY THE CARD IS ALWAYS THERE.
    #
    # Twice now this has been hidden from somebody who was looking for it.
    # First it was gated on `authenticated`, which hid it from an operator
    # holding the admin key. Then on `is_librarian`, which hid it from
    # somebody holding the LIBRARIAN CODE -- and that is how everybody
    # reaches this page today, because SSO is not finished. A code-holder
    # has no caller at all: the code is neither a session nor the admin
    # token, so `whoami` returns None and every attribute is False.
    #
    # Hiding a card is the one thing that cannot tell the reader anything.
    # It renders either way now, and says which it is.
    #
    # The code deliberately does NOT open it. That code is shareable to
    # any member of library staff; the eight people meant to read real
    # patron conversations are named in SSO_LIBRARIAN_UIDS. So the answer
    # for a code-holder is "sign in", not "here you go" -- and the link
    # below becomes a working button the moment the IdP is configured,
    # with no change here.
    may_read = getattr(caller, "is_librarian", False)
    reading = _card(
        "What patrons asked",
        "Every real question since the bot opened, and what it answered. "
        "Our own testing is left out."
        if may_read else
        "Every real question since the bot opened, and what it answered. "
        "Reading these needs your Miami sign-in — the access code for this "
        "page is shared with all library staff, and these are patrons' own "
        "words.",
        ui.action("/librarian/conversations", "Open", primary=True)
        if may_read else
        ui.action("/admin/sso/login?next=/librarian/conversations",
                  "Sign in with Miami", primary=True))

    report = _card(
        "Report a wrong answer",
        "Goes straight to the maintainer. Nothing comes back to you.",
        ui.action(f"/librarian/ticket{k}", "Open the form"))

    if marked:
        testing = _card(
            "Test mode is ON for this browser",
            "Questions you ask are recorded as testing, not as a "
            "student's. It ends when you close the browser.",
            ui.action("/librarian/staff-test/off", "Turn it off"), on=True)
    else:
        testing = _card(
            "Trying the bot rather than using it?",
            "One click marks this browser so your questions are not "
            "counted as a student's. Same bot, same answers.",
            ui.action("/librarian/staff-test",
                      "Turn on test mode and open the chatbot"))

    body = (
        "<h1>Smart Chatbot &mdash; staff hub</h1>"
        f"{reading}{report}{testing}"
        "<p><small class='dim'>Bookmark this page &mdash; the links carry "
        "the access code.</small></p>"
    )
    return ui.page("Staff hub", body, chrome=False)


def build_hub_router(deps: dict):
    from fastapi import APIRouter, Depends, HTTPException  # type: ignore
    from fastapi.responses import HTMLResponse  # type: ignore

    admin_token: str = (deps.get("admin_token") or "").strip()

    async def _key_only(request: Request):
        """Fallback for a deployment with no SSO guard wired in -- the
        shape this had before 2026-09-01."""
        from src.api.admin.sso import Caller, ROLE_OPERATOR

        supplied = request.query_params.get("key", "")
        if not admin_token or supplied != admin_token:
            raise HTTPException(status_code=401,
                                detail="admin token required")
        return Caller(role=ROLE_OPERATOR, via="token")

    guard = deps.get("guard") or _key_only
    librarian_code: str = (deps.get("librarian_code") or "").strip()

    async def _nobody():
        return None

    # Who is looking, not whether to answer -- the code still gates this
    # page. It only decides whether somebody is offered the transcripts.
    whoami = deps.get("whoami") or _nobody
    db = deps.get("db")
    router = APIRouter(tags=["hub"])

    @router.get("/admin/", response_class=HTMLResponse)
    @router.get("/admin", response_class=HTMLResponse, include_in_schema=False)
    async def admin_hub(request: Request, caller=Depends(guard)):
        """THE LANDING PAGE WENT THROUGH THE SHARED GUARD LAST.

        Every other admin surface uses make_admin_guard and redirects to
        Miami sign-in. This one compared the key by hand and never asked
        SSO at all, so with SSO_ENABLED on, /admin/conversations bounced
        to the IdP and /admin/ -- the page everybody opens first --
        answered `{"detail":"admin token required"}` as raw JSON.

        Miami IT hit exactly that on 2026-09-01: told to test
        https://chatbot.lib.miamioh.edu/admin, they got the JSON.
        """
        # The links drop the key ONLY for an authenticated session.
        #
        # Stated that way round on purpose. Asking instead whether the
        # caller arrived `via == "token"` means any guard that returns no
        # caller at all -- a deployment without SSO, a test double --
        # silently renders a whole nav that drops the key, which is the
        # dead-link bug test_nav_carries_the_key exists to catch. Only a
        # signed-in operator has something better than the key to travel
        # on; everybody else keeps whatever they arrived with.
        supplied = ("" if getattr(caller, "authenticated", False)
                    else request.query_params.get("key", ""))
        counts = None
        if db is not None:
            from src.api.admin.review_queries import dashboard_counts
            counts = await dashboard_counts(db)
        return HTMLResponse(
            render_admin_hub(supplied, librarian_code, caller, counts))

    @router.get("/librarian/", response_class=HTMLResponse)
    @router.get("/librarian", response_class=HTMLResponse, include_in_schema=False)
    async def librarian_hub(request: Request, caller=Depends(whoami)):
        supplied = request.query_params.get("key", "")
        # Either door: the shareable code, which reaches any member of
        # library staff, or a Miami session for somebody on the librarian
        # or operator list. Making a department head paste a code they
        # have no reason to know, on a console their own sign-in already
        # admits them to, is a step that exists for nobody.
        if getattr(caller, "authenticated", False) and getattr(
                caller, "is_librarian", False):
            pass
        elif not librarian_code or supplied != librarian_code:
            raise HTTPException(
                status_code=401,
                detail="Missing or wrong access code. Ask the library web "
                       "services team for the staff-hub link.",
            )
        from src.api.staff_test import STAFF, origin_from_cookie_header

        marked = origin_from_cookie_header(
            request.headers.get("cookie")) == STAFF
        return HTMLResponse(render_librarian_hub(supplied, caller, marked))

    return router
