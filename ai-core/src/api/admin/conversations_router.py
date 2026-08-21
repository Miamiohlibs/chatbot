"""Conversations by day -- "what did people ask today".

WHY A SEPARATE SURFACE
    /admin/review answers "which turns look wrong": it lists MESSAGES,
    filtered by type (thumbs-down, refusal, low confidence...), newest first,
    across all time. That is the right shape for triage and the wrong shape
    for the question an operator actually asks most mornings, which is what
    happened yesterday. Getting there meant opening Flagged, switching to the
    `all` preset, and scrolling a mixed feed reading timestamps.

    This lists CONVERSATIONS, one row each, for one day, in Oxford time.

OXFORD TIME
    The day boundary is the library's, not UTC's. A UTC midnight cuts the
    Oxford evening in half, and evening is when the building is busiest --
    the cost dashboard had exactly this bug and carries the same note.
"""

from __future__ import annotations

import datetime as dt
import html
from typing import Any

from src.api.admin import admin_ui as ui
from src.api.admin.review_queries import (
    LIBRARY_TZ,
    conversation_days,
    list_conversations_on,
)

_e = ui.e


def today_local() -> str:
    from zoneinfo import ZoneInfo

    return dt.datetime.now(ZoneInfo(LIBRARY_TZ)).date().isoformat()


def shift_day(day: str, delta: int) -> str:
    try:
        y, m, d = (int(p) for p in day.split("-"))
        return (dt.date(y, m, d) + dt.timedelta(days=delta)).isoformat()
    except Exception:  # noqa: BLE001
        return today_local()


def build_conversations_router(deps: dict) -> Any:
    """deps: {db, guard}."""
    try:
        from fastapi import APIRouter, Depends  # type: ignore
        from fastapi.responses import HTMLResponse  # type: ignore
    except ImportError:  # pragma: no cover
        class _P:
            prefix = "/admin/conversations"
            routes: list = []
        return _P()

    router = APIRouter(tags=["admin"])
    db = deps["db"]
    guard = deps["guard"]

    @router.get("/admin/conversations", response_class=HTMLResponse)
    async def conversations(day: str = "", key: str = "",
                            _g=Depends(guard)) -> Any:
        day = day or today_local()
        kq = f"&key={_e(key)}" if key else ""
        rows = await list_conversations_on(db, day)
        days = await conversation_days(db)

        is_today = day == today_local()
        prev_d, next_d = shift_day(day, -1), shift_day(day, 1)
        # No forward arrow past today: an empty page for tomorrow reads as a
        # data problem rather than as a calendar you walked off the end of.
        nav = (
            f"<a class='tag' href='/admin/conversations?day={_e(prev_d)}{kq}'>"
            f"&larr; {_e(prev_d)}</a> "
            f"<b style='margin:0 .6rem'>{_e(day)}"
            f"{' (today)' if is_today else ''}</b> "
            + ("" if next_d > today_local() else
               f"<a class='tag' href='/admin/conversations?day={_e(next_d)}{kq}'>"
               f"{_e(next_d)} &rarr;</a> ")
            + ("" if is_today else
               f"<a class='tag' href='/admin/conversations{('?key=' + _e(key)) if key else ''}'>"
               f"today</a>")
        )

        recent = " ".join(
            f"<a class='tag{' active' if d['day'] == day else ''}' "
            f"href='/admin/conversations?day={_e(d['day'])}{kq}'>"
            f"{_e(d['day'][5:])} <span class='dim'>{d['questions']}</span></a>"
            for d in days[:14]
        )

        if not rows:
            body = (
                f"<h1>Conversations</h1><div style='margin:.6rem 0'>{nav}</div>"
                f"<p class='dim'>Nobody asked anything on {_e(day)}.</p>"
                f"<div style='margin-top:1rem'>{recent}</div>"
            )
            return HTMLResponse(ui.page("Conversations", body,
                                        current="/admin/conversations", key=key))

        def row(r: dict) -> str:
            flags = []
            if r["refusals"]:
                flags.append(f"<span class='tag refusal'>{r['refusals']} refused</span>")
            if r["thumbs_down"]:
                flags.append(f"<span class='tag thumbs_down'>{r['thumbs_down']} 👎</span>")
            if r["thumbs_up"]:
                flags.append(f"<span class='tag thumbs_up'>{r['thumbs_up']} 👍</span>")
            if r["low_confidence"]:
                flags.append("<span class='tag low_confidence'>low confidence</span>")
            more = (f" <span class='dim'>+{r['asked'] - 1} more</span>"
                    if r["asked"] > 1 else "")
            href = (f"/admin/review/{_e(r['conversation_id'])}"
                    f"{('?key=' + _e(key)) if key else ''}")
            return (
                f"<tr{' class=needs' if r['needs_look'] else ''}>"
                f"<td class='num'>{_e(r['opened_hm'])}</td>"
                f"<td><a href='{href}'>{_e(r['first_question'][:110])}</a>{more}</td>"
                f"<td class='num'>{r['asked']}</td>"
                f"<td>{' '.join(flags)}</td></tr>"
            )

        needs = sum(1 for r in rows if r["needs_look"])
        body = (
            f"<h1>Conversations</h1>"
            f"<div style='margin:.6rem 0'>{nav}</div>"
            f"<p class='dim'>{len(rows)} conversation(s), "
            f"{sum(r['asked'] for r in rows)} question(s)"
            + (f" &middot; <b>{needs}</b> worth a look" if needs else "")
            + "</p>"
            f"<style>tr.needs td{{background:#fffaf5}}"
            f"td.num{{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}}"
            f"</style>"
            f"<table><tr><th>Time</th><th>First question</th>"
            f"<th>Asked</th><th></th></tr>"
            + "".join(row(r) for r in rows) + "</table>"
            f"<h2 style='font-size:.95rem;margin-top:1.4rem'>Other days</h2>"
            f"<div>{recent}</div>"
        )
        return HTMLResponse(ui.page("Conversations", body,
                                    current="/admin/conversations", key=key))

    return router


__all__ = ["build_conversations_router", "shift_day", "today_local"]
