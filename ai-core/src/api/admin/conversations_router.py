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
from urllib.parse import quote

from src.api.admin.review_queries import (
    search_messages,
    BETA_START_LOCAL,
    LIBRARY_TZ,
    SOURCE_TAGS,
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
                            per: int = 50, source: str = "",
                            _g=Depends(guard)) -> Any:
        day = day or today_local()
        page = max(1, page)
        per = min(max(per, 10), 200)
        source = source if source in {t for t, _ in SOURCE_TAGS} else ""
        kq = f"&key={_e(key)}" if key else ""
        sq = f"&source={_e(source)}" if source else ""
        res = await list_conversations_on(db, day, limit=per,
                                          offset=(page - 1) * per,
                                          source=source)
        rows, total = res["rows"], res["total"]
        days = await conversation_days(db)

        is_today = day == today_local()
        prev_d, next_d = shift_day(day, -1), shift_day(day, 1)
        # No forward arrow past today: an empty page for tomorrow reads as a
        # data problem rather than as a calendar you walked off the end of.
        nav = (
            ("" if day <= BETA_START_LOCAL[:10] else
               f"<a class='tag' href='/admin/conversations?day={_e(prev_d)}{kq}'>"
               f"&larr; {_e(prev_d)}</a> ")
            + f"<b style='margin:0 .6rem'>{_e(day)}"
            f"{' (today)' if is_today else ''}</b> "
            + ("" if next_d > today_local() else
               f"<a class='tag' href='/admin/conversations?day={_e(next_d)}{kq}'>"
               f"{_e(next_d)} &rarr;</a> ")
            + ("" if is_today else
               f"<a class='tag' href='/admin/conversations{('?key=' + _e(key)) if key else ''}'>"
               f"today</a>")
        )

        # Every source is a link: clicking one shows that group. The count
        # is the whole day for that source, not the page.
        counts = res.get("source_counts") or {}
        source_bar = " ".join(
            f"<a class='tag{' active' if t == source else ''}' "
            f"href='/admin/conversations?day={_e(day)}{('&source=' + t) if t else ''}"
            f"{kq}'>{_e(label)}"
            + (f" <span class='dim'>{counts[t]}</span>" if counts.get(t) else "")
            + "</a>"
            for t, label in SOURCE_TAGS
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
                f"&per={per}{sq}{kq}", status_code=303)

        def pager() -> str:
            if pages <= 1:
                return ""
            first = (page - 1) * per + 1
            last = min(page * per, total)
            def lnk(p: int, label: str, disabled: bool) -> str:
                if disabled:
                    return f"<span class='tag dim'>{label}</span>"
                return (f"<a class='tag' href='/admin/conversations?day={_e(day)}"
                        f"&page={p}&per={per}{sq}{kq}'>{label}</a>")
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
            gone = ("The bot went live to the public at 6:00pm on 13 August. "
                    "Days before that are development and staff rehearsal, "
                    "and are not shown here."
                    if res.get("before_beta") else
                    f"Nobody asked anything on {_e(day)}.")
            body = (
                f"<h1>Conversations</h1><div style='margin:.6rem 0'>{nav}</div>"
                f"<p class='dim'>{gone}</p>"
                f"<div style='margin-top:1rem'>{recent}</div>"
            )
            return HTMLResponse(ui.page("Conversations", body,
                                        current="/admin/conversations", key=key))

        _SRC_CLASS = {"staff": "thumbs_up", "local": "refusal",
                      "maybe-staff": "low_confidence",
                      "patron-confirmed": "thumbs_up"}

        def set_link(cid: str, value: str, text: str, title: str) -> str:
            return (f"<a class='setsrc' title='{_e(title)}' "
                    f"href='/admin/conversations/{_e(cid)}/source"
                    f"?set={value}&day={_e(day)}{sq}"
                    f"{('&key=' + _e(key)) if key else ''}'>{text}</a>")

        def source_cell(r: dict) -> str:
            """Its own column, not a flag.

            Mixing "who was this" into the same row of chips as "this answer
            was refused" made the operator read two unrelated questions out
            of one line. They are different questions and they get different
            columns.
            """
            src = r.get("source") or {}
            cid = r["conversation_id"]

            # Three one-click verdicts on every row. A rule that cannot be
            # corrected by the person reading it is a rule they will stop
            # trusting; these override everything, including the recorded
            # facts, because the reader can know things the data cannot
            # hold.
            controls = (
                "<span class='setsrcs'>"
                + set_link(cid, "local", "S", "Mark as a script / local test")
                + set_link(cid, "staff", "T", "Mark as staff testing")
                + set_link(cid, "patron", "P", "Confirm this was a patron")
                + (set_link(cid, "", "×", "Clear the manual verdict")
                   if src.get("manual") else "")
                + "</span>")

            if not src.get("label"):
                return f"<span class='dim'>&mdash;</span> {controls}"
            cls = _SRC_CLASS.get(src.get("tag", ""), "low_confidence")
            mark = " ✓" if src.get("manual") else ""
            return (f"<a class='tag {cls}' title='{_e(src.get('why', ''))}' "
                    f"href='/admin/conversations?day={_e(day)}"
                    f"&source={_e(src.get('tag', ''))}{kq}'>"
                    f"{_e(src['label'])}{mark}</a> {controls}")

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
                f"<td>{source_cell(r)}</td>"
                f"<td><a href='{href}'>{_e(r['first_question'][:110])}</a>{more}</td>"
                f"<td class='num'>{r['asked']}</td>"
                f"<td>{' '.join(flags)}</td></tr>"
            )

        needs = sum(1 for r in rows if r["needs_look"])
        # The console had no keyword search anywhere. Conversations browse
        # one day at a time, Flagged filters by preset, tickets by status --
        # so "has anyone ever asked about Zotero" meant opening days one
        # after another and reading them. The box goes here because this is
        # the page an operator is already on when the question occurs.
        search_box = (
            f"<form method='get' action='/admin/search' class='searchbar' "
            f"style='margin:.6rem 0;display:flex;gap:.4rem;flex-wrap:wrap'>"
            + (f"<input type='hidden' name='key' value='{_e(key)}'>" if key else "")
            + f"<input type='search' name='q' placeholder='Search every "
              f"conversation…' aria-label='Search conversations' "
              f"style='flex:1;min-width:14rem'>"
              f"<select name='who' aria-label='Whose words'>"
              f"<option value='any'>anyone</option>"
              f"<option value='patron'>what patrons typed</option>"
              f"<option value='bot'>what the bot said</option></select>"
              f"<button type='submit'>Search</button></form>"
        )
        body = (
            f"<h1>Conversations</h1>"
            f"{search_box}"
            f"<div style='margin:.6rem 0'>{nav}</div>"
            f"<div class='filter-bar'>{source_bar}</div>"
            + (f"<p class='dim'>13 August is shown from 6:00pm, when the "
               f"bot went live to the public.</p>"
               if day == BETA_START_LOCAL[:10] else "")
            + f"<p class='dim'>{total} conversation(s) on this day"
            + (f" &middot; <b>{needs}</b> on this page worth a look" if needs else "")
            + " &middot; <span title='A label is only shown when something in "
              "the transcript supports it. No label means nothing does — the "
              "system stores no identity, so “patron” is never asserted. "
              "S / T / P on any row set it by hand and override every rule; "
              "a ✓ means somebody did.'>"
              "how sources are labelled</span></p>"
            + pager()
            # Scoped under .convs: an unscoped `td.num` or `tr.needs td`
            # lands after the shared stylesheet and restyles every table in
            # the console, including the one on the page you navigate to next.
            + f"<style>.convs tr.needs td{{background:#fffaf5}}"
            f".convs .setsrcs{{white-space:nowrap;margin-left:.35rem}}"
            f".convs .setsrc{{display:inline-block;width:1.15rem;"
            f"text-align:center;font-size:.7rem;line-height:1.15rem;"
            f"border:1px solid var(--line);border-radius:3px;color:var(--muted);"
            f"text-decoration:none;margin-left:.1rem}}"
            f".convs .setsrc:hover{{background:var(--miami);color:#fff;"
            f"border-color:var(--miami)}}"
            f".convs td.num{{text-align:right;white-space:nowrap;"
            f"font-variant-numeric:tabular-nums}}</style>"
            f"<table><tr><th>Time</th><th>Source</th><th>First question</th>"
            f"<th>Asked</th><th></th></tr>"
            + "".join(row(r) for r in rows) + "</table>"
            + pager()
            + f"<h2 style='font-size:.95rem;margin-top:1.4rem'>Other days</h2>"
            f"<div>{recent}</div>"
        )
        return HTMLResponse(ui.page("Conversations",
                                    f"<div class='convs'>{body}</div>",
                                    current="/admin/conversations", key=key))


    @router.get("/admin/search", response_class=HTMLResponse)
    async def search(q: str = "", who: str = "any", key: str = "",
                     page: int = 1, per: int = 50,
                     _g=Depends(guard)) -> Any:
        """Keyword search across every conversation held.

        One row per CONVERSATION, not per matching message: ten hits in one
        chat is one thing to read, not ten.
        """
        who = who if who in {"any", "patron", "bot"} else "any"
        page = max(1, page)
        per = min(max(per, 10), 200)
        kq = f"&key={_e(key)}" if key else ""
        res = await search_messages(db, q, who=who, limit=per,
                                    offset=(page - 1) * per)
        rows, total = res["rows"], res["total"]

        who_bar = "".join(
            (f"<b class='tag'>{_e(label)}</b>" if who == value else
             f"<a class='tag' href='/admin/search?q={quote(res['query'])}"
             f"&who={value}{kq}'>{_e(label)}</a>")
            for value, label in (("any", "anyone"),
                                 ("patron", "what patrons typed"),
                                 ("bot", "what the bot said"))
        )

        form = (
            f"<form method='get' action='/admin/search' "
            f"style='margin:.6rem 0;display:flex;gap:.4rem;flex-wrap:wrap'>"
            + (f"<input type='hidden' name='key' value='{_e(key)}'>" if key else "")
            + f"<input type='hidden' name='who' value='{_e(who)}'>"
            f"<input type='search' name='q' value='{_e(res['query'])}' "
            f"placeholder='Search every conversation…' "
            f"aria-label='Search conversations' style='flex:1;min-width:14rem'>"
            f"<button type='submit'>Search</button></form>"
        )

        if res.get("error"):
            note = ("<div class='card attn'>The search could not run. The "
                    "console log has the reason.</div>")
        elif not res["query"]:
            note = ("<p class='dim'>Type at least two characters. Matching is "
                    "plain substring, case-insensitive — no wildcards, no "
                    "operators.</p>")
        elif not rows:
            note = (f"<p class='dim'>Nothing matches "
                    f"<b>{_e(res['query'])}</b>. Only conversations still "
                    f"held are searched.</p>")
        else:
            note = (f"<p class='dim'>{total} conversation(s) contain "
                    f"<b>{_e(res['query'])}</b>."
                    + (" <b>Truncated</b> — more matched than this page can "
                       "reach, so narrow the words rather than reading on."
                       if res["truncated"] else "")
                    + "</p>")

        def row(r: dict) -> str:
            more = (f" <span class='dim'>+{r['hits'] - 1} more in this "
                    f"chat</span>" if r["hits"] > 1 else "")
            return (
                f"<tr><td class='dim' style='white-space:nowrap'>"
                f"{_e(r['when'])}</td>"
                f"<td><a href='/admin/review/{_e(r['conversation_id'])}"
                f"{('?key=' + _e(key)) if key else ''}'>{_e(r['snippet'])}</a>"
                f"{more}</td>"
                f"<td class='dim'>{_e(r['snippet_from'])}</td></tr>"
            )

        pages = max(1, -(-total // per))
        pager = ""
        if pages > 1:
            bits = []
            if page > 1:
                bits.append(f"<a class='tag' href='/admin/search?"
                            f"q={quote(res['query'])}&who={who}&page={page - 1}"
                            f"{kq}'>&larr; previous</a>")
            bits.append(f"<span class='dim'>page {page} of {pages}</span>")
            if page < pages:
                bits.append(f"<a class='tag' href='/admin/search?"
                            f"q={quote(res['query'])}&who={who}&page={page + 1}"
                            f"{kq}'>next &rarr;</a>")
            pager = f"<div style='margin:.6rem 0'>{' '.join(bits)}</div>"

        table = ("" if not rows else
                 f"<table><tr><th>When</th><th>Match</th><th>Said by</th></tr>"
                 + "".join(row(r) for r in rows) + "</table>")
        body = (f"<h1>Search</h1>{form}"
                f"<div class='filter-bar'>{who_bar}</div>"
                f"{note}{pager}{table}{pager}")
        return HTMLResponse(ui.page("Search", body,
                                    current="/admin/conversations", key=key))

    @router.get("/admin/conversations/{conversation_id}/source",
                response_class=HTMLResponse)
    async def set_source(conversation_id: str, set: str = "", day: str = "",
                         key: str = "", source: str = "",
                         _g=Depends(guard)) -> Any:
        """Record, or clear, a person's verdict on one conversation.

        A GET from a link on the row it concerns. Reversible in one click,
        so it needs no confirmation step; making somebody confirm a label
        they can undo is how a correction stops being worth making.
        """
        from fastapi.responses import RedirectResponse

        from src.api.admin.review_queries import MANUAL_LABELS

        value = (set or "").strip().lower()
        data: dict
        if value in MANUAL_LABELS:
            data = {"sourceOverride": value,
                    "sourceOverrideBy": "operator",
                    "sourceOverrideAt": dt.datetime.now(dt.timezone.utc)}
        elif value == "":
            data = {"sourceOverride": None, "sourceOverrideBy": None,
                    "sourceOverrideAt": None}
        else:
            data = {}

        if data:
            try:
                await db.conversation.update(
                    where={"id": conversation_id}, data=data)
            except Exception:  # noqa: BLE001 -- a failed label must not 500
                import logging
                logging.getLogger(__name__).warning(
                    "could not set the source verdict on %s",
                    conversation_id, exc_info=True)

        back = (f"/admin/conversations?day={_e(day or today_local())}"
                + (f"&source={_e(source)}" if source else "")
                + (f"&key={_e(key)}" if key else ""))
        return RedirectResponse(back, status_code=303)

    return router


__all__ = ["build_conversations_router", "shift_day", "today_local"]
