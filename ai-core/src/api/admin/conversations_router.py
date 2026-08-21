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
    async def conversations(day: str = "", key: str = "", page: int = 1,
                            per: int = 50, _g=Depends(guard)) -> Any:
        day = day or today_local()
        page = max(1, page)
        per = min(max(per, 10), 200)
        kq = f"&key={_e(key)}" if key else ""
        res = await list_conversations_on(db, day, limit=per,
                                          offset=(page - 1) * per)
        rows, total = res["rows"], res["total"]
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

        pages = max(1, -(-total // per))
        if page > pages and total:
            # Landing past the end reads as "no data" rather than "wrong
            # page number", so send them to the last real page instead.
            from fastapi.responses import RedirectResponse
            return RedirectResponse(
                f"/admin/conversations?day={_e(day)}&page={pages}"
                f"&per={per}{kq}", status_code=303)

        def pager() -> str:
            if pages <= 1:
                return ""
            first = (page - 1) * per + 1
            last = min(page * per, total)
            def lnk(p: int, label: str, disabled: bool) -> str:
                if disabled:
                    return f"<span class='tag dim'>{label}</span>"
                return (f"<a class='tag' href='/admin/conversations?day={_e(day)}"
                        f"&page={p}&per={per}{kq}'>{label}</a>")
            return (
                f"<div style='margin:.8rem 0'>"
                f"{lnk(1, '&laquo; first', page == 1)} "
                f"{lnk(page - 1, '&lsaquo; prev', page == 1)} "
                f"<span class='dim' style='margin:0 .5rem'>"
                f"{first}&ndash;{last} of {total}</span> "
                f"{lnk(page + 1, 'next &rsaquo;', page >= pages)} "
                f"{lnk(pages, 'last &raquo;', page >= pages)}</div>"
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
            src = r.get("source") or {}
            if src.get("label"):
                cls = "refusal" if src["label"] == "local test" else "low_confidence"
                # title= carries the reason, so a label nobody can explain
                # never appears on this page.
                flags.append(f"<span class='tag {cls}' title='{_e(src['why'])}'>"
                             f"{_e(src['label'])}</span>")
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
            f"<p class='dim'>{total} conversation(s) on this day"
            + (f" &middot; <b>{needs}</b> on this page worth a look" if needs else "")
            + " &middot; <span title='A label is only shown when something in "
              "the transcript supports it. No label means nothing does — the "
              "system stores no identity, so “patron” is never asserted.'>"
              "how sources are labelled</span></p>"
            + pager()
            # Scoped under .convs: an unscoped `td.num` or `tr.needs td`
            # lands after the shared stylesheet and restyles every table in
            # the console, including the one on the page you navigate to next.
            + f"<style>.convs tr.needs td{{background:#fffaf5}}"
            f".convs td.num{{text-align:right;white-space:nowrap;"
            f"font-variant-numeric:tabular-nums}}</style>"
            f"<table><tr><th>Time</th><th>First question</th>"
            f"<th>Asked</th><th></th></tr>"
            + "".join(row(r) for r in rows) + "</table>"
            + pager()
            + f"<h2 style='font-size:.95rem;margin-top:1.4rem'>Other days</h2>"
            f"<div>{recent}</div>"
        )
        return HTMLResponse(ui.page("Conversations",
                                    f"<div class='convs'>{body}</div>",
                                    current="/admin/conversations", key=key))

    return router


__all__ = ["build_conversations_router", "shift_day", "today_local"]
