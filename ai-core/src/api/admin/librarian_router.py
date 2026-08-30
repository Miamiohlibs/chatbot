"""The librarian console: what patrons asked, and a way to say it was wrong.

WHY THIS IS A SEPARATE SURFACE
    One console served two jobs. A subject librarian wants to know what
    students asked about her subject this week and to report an answer that
    was wrong. Nobody on the library staff needs the spend ladder, the kill
    switch, or a button that rebuilds the index for seven minutes -- and a
    console that shows you six controls you must not touch is a console you
    stop reading.

    Operator, 2026-08-30: split the librarian form and the day's real
    questions into one part to hand out, and keep everything else -- every
    conversation including our own testing, and all the controls -- inside
    the group.

WHAT "REAL" MEANS HERE, AND WHY IT IS NOT A FILTER SHE CAN CHANGE
    Most of what is in the message table is us: staff testing, replays, the
    eval harness. Handed the raw list, a librarian would spend the first
    minute working out which rows were real, and would reasonably conclude
    the bot gets ten questions a day from her own colleagues. So the scope
    is fixed in the query rather than offered as a chip -- see
    `real_patrons_only` in review_queries.

    The operator console still shows everything, labelled, and is still
    where a mislabelled conversation gets corrected.

ON PII
    These are real patron questions, and people type things into a chat box
    that they would not put in an email. That was the operator's decision
    and it is the right one -- a librarian cannot judge an answer she is not
    allowed to read. What follows from it is that this surface is behind the
    same sign-in as the rest of the console, is never indexable, and shows
    the transcript and nothing beside it: no addresses, no session, no
    token accounting.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Optional

try:
    from starlette.requests import Request  # type: ignore
except Exception:  # noqa: BLE001
    Request = Any  # type: ignore

from src.api.admin import admin_ui as ui
from src.api.admin.conversations_router import shift_day, today_local
from src.api.admin.review_queries import (
    conversation_detail,
    list_conversations_on,
    local_ts,
)
from src.api.admin.sso import ROLE_LIBRARIAN

logger = logging.getLogger(__name__)

_NOINDEX = {"X-Robots-Tag": "noindex, nofollow, noarchive"}

# How far back the quick ranges reach. Deliberately short: the question a
# librarian arrives with is "what happened lately", and a year of history
# on a 4 GB box is a page that takes ten seconds to draw.
_RANGES = ((0, "Today"), (6, "Last 7 days"), (29, "Last 30 days"))


def _kq(key: str) -> str:
    return f"&key={ui.e(key)}" if key else ""


def _row(c: dict, key: str) -> str:
    qs = c.get("questions") or []
    first = qs[0] if qs else ""
    more = (f"<span class='dim'> +{len(qs) - 1} more</span>"
            if len(qs) > 1 else "")
    when = local_ts(c.get("first_ts"))
    flags = []
    if c.get("thumbs_down"):
        flags.append("<span class='tag down'>thumbs down</span>")
    if c.get("refusals"):
        flags.append("<span class='tag refuse'>could not answer</span>")
    if c.get("low_confidence"):
        flags.append("<span class='tag low-conf'>unsure</span>")
    if c.get("thumbs_up"):
        flags.append("<span class='tag up'>thumbs up</span>")
    return (
        f"<tr><td style='white-space:nowrap'>{ui.e(when)}</td>"
        f"<td><a href='/librarian/conversations/"
        f"{ui.e(c.get('conversation_id'))}?key={ui.e(key)}'>"
        f"{ui.e(first)}</a>{more}</td>"
        f"<td style='white-space:nowrap'>{' '.join(flags)}</td></tr>"
    )


def render_list(rows: dict, *, key: str, day: str, day_to: str,
                caller=None) -> str:
    today = today_local()
    chips = []
    for back, label in _RANGES:
        frm = shift_day(today, -back)
        on = " active" if (day == frm and day_to == today) else ""
        chips.append(f"<a class='tag{on}' href='/librarian/conversations"
                     f"?day={frm}&day_to={today}{_kq(key)}'>"
                     f"{ui.e(label)}</a>")

    total = rows.get("total", 0)
    listing = rows.get("rows") or []

    if rows.get("before_beta"):
        body = ui.empty("The bot was not open to patrons yet on that date.")
    elif not listing:
        body = ui.empty("No patron questions in this range. Our own testing "
                        "is not shown here.")
    else:
        body = ("<div class='scroll-table'><table>"
                "<thead><tr><th>When</th><th>What they asked</th>"
                "<th>How it went</th></tr></thead><tbody>"
                + "".join(_row(c, key) for c in listing)
                + "</tbody></table></div>")

    clamp = ("<p class='hint'>That range was longer than this page will "
             "draw at once, so it was shortened.</p>"
             if rows.get("clamped") else "")

    return ui.page(
        "Real questions",
        "<h1>What patrons asked</h1>"
        "<p class='lede'>Real questions from the library website. Our own "
        "testing, replays and the evaluation harness are left out — this "
        "is what people actually asked.</p>"
        f"<div class='filter-bar'>{''.join(chips)}</div>"
        f"<p class='hint'>{total} conversation(s) in this range.</p>"
        + body + clamp,
        current="/librarian/conversations", key=key, who=caller,
        role=ROLE_LIBRARIAN)


def _turn(m: dict, conv_id: str, key: str) -> str:
    role = "Patron" if m.get("role") == "user" else "Chatbot"
    cls = "" if m.get("role") == "user" else " assistant"
    flag = ("<span class='tag refuse'>could not answer</span>"
            if m.get("was_refusal") else "")
    report = ""
    if m.get("role") == "assistant":
        # The whole point of letting a librarian read this. Reporting from
        # here carries the conversation with it, so the form is not a blank
        # page asking her to describe what she is looking at.
        report = (f"<div class='acts'><a class='btn ghost' "
                  f"href='/librarian/ticket?conversation_id={ui.e(conv_id)}"
                  f"&message_id={ui.e(m.get('id'))}'>"
                  f"This answer is wrong</a></div>")
    return (
        f"<div class='msg{cls}'>"
        f"<div class='msg-hd'><span class='role'>{role}</span>"
        f"<span class='time'>{ui.e(m.get('time'))}</span>{flag}</div>"
        f"<div class='body'>{ui.e(m.get('content'))}</div>{report}</div>"
    )


def render_detail(d: Optional[dict], *, key: str, caller=None) -> str:
    if d is None:
        return ui.page(
            "Conversation", "<h1>Not found</h1>"
            "<p class='lede'>No conversation with that reference. It may "
            "have been a link from an older page.</p>"
            f"<div class='acts'><a class='btn' href='/librarian/conversations"
            f"?key={ui.e(key)}'>Back to the list</a></div>",
            current="/librarian/conversations", key=key, who=caller,
            role=ROLE_LIBRARIAN)

    turns = "".join(_turn(m, d["conversation_id"], key)
                    for m in (d.get("messages") or []))
    return ui.page(
        "Conversation",
        "<h1>One conversation</h1>"
        f"<p class='lede'>{ui.e(d.get('created_at'))} — read it the way the "
        f"patron saw it. If an answer is wrong, say so from the turn it is "
        f"on and the report arrives with this conversation attached.</p>"
        f"{turns}"
        f"<div class='acts'><a class='btn' href='/librarian/conversations"
        f"?key={ui.e(key)}'>Back to the list</a></div>",
        current="/librarian/conversations", key=key, who=caller,
        role=ROLE_LIBRARIAN)


def build_librarian_router(deps: dict):
    from fastapi import APIRouter, Depends  # type: ignore
    from fastapi.responses import HTMLResponse  # type: ignore

    db = deps.get("db")
    guard = deps.get("librarian_guard") or deps.get("guard")
    router = APIRouter(prefix="/librarian", tags=["librarian"])

    if guard is None:
        async def guard() -> None:  # noqa: D401 -- mounted only behind one
            return None

    @router.get("/conversations", response_class=HTMLResponse)
    async def conversations(key: str = "", day: str = "", day_to: str = "",
                            page: int = 1, per: int = 50,
                            caller=Depends(guard)):
        today = today_local()
        # Default to a week rather than to today. A subject librarian does
        # not open this every morning; landing on an empty page because it
        # is 9am is the version of this that gets bookmarked once and never
        # opened again.
        day = day or shift_day(today, -6)
        day_to = day_to or today
        page, per, offset = ui.page_bounds(page, per, per_max=200)
        rows = await list_conversations_on(
            db, day, day_to=day_to, limit=per, offset=offset,
            real_patrons_only=True)
        return HTMLResponse(
            render_list(rows, key=key, day=day, day_to=day_to, caller=caller),
            headers=_NOINDEX)

    @router.get("/conversations/{conversation_id}",
                response_class=HTMLResponse)
    async def conversation(conversation_id: str, key: str = "",
                           caller=Depends(guard)):
        d = await conversation_detail(db, conversation_id)
        return HTMLResponse(render_detail(d, key=key, caller=caller),
                            headers=_NOINDEX)

    return router
