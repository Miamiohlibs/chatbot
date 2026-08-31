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

import re as _re

from src.api.admin.review_queries import (
    MAX_DAY_SPAN,
    canonical_source,
    attach_feedback,
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


# The three reasons a turn is worth a look, plus the one positive signal.
# These were /admin/review's presets. Bringing them here is what made that
# page redundant -- see the note on the redirect below.
_FLAG_TAGS = (
    ("refusal", "refused"),
    ("thumbs_down", "thumbs-down"),
    ("low_confidence", "low confidence"),
    ("thumbs_up", "thumbs-up"),
)
_FLAG_TAGS_BY_VALUE = {v for v, _ in _FLAG_TAGS}

_DATE_RE = _re.compile(r"^\d{4}-\d{2}-\d{2}$")
"""A date input can be typed by hand. Anything that is not a date is read
as "no range" rather than handed to the parser to raise on."""


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
                            to: str = "", needs: int = 0, flag: str = "",
                            caller=Depends(guard)) -> Any:
        day = day or today_local()
        page = max(1, page)
        per = min(max(per, 10), 200)
        # The retired `local` is mapped onto `bot` inside
        # list_conversations_on, so a bookmarked ?source=local still lands
        # where it used to. Validated against the alias too, or the filter
        # would be dropped before it ever got there.
        source = (source if canonical_source(source)
                  in {t for t, _ in SOURCE_TAGS} else "")
        # `to` makes this a range and `needs` narrows it to the turns
        # something went wrong in -- together, the two things Flagged could
        # do that this page could not.
        to = to if _DATE_RE.match(to or "") else ""
        needs_only = bool(needs)
        flag = flag if flag in _FLAG_TAGS_BY_VALUE else ""
        kq = f"&key={_e(key)}" if key else ""
        sq = f"&source={_e(source)}" if source else ""
        rq = f"&to={_e(to)}" if to else ""
        nq = "&needs=1" if needs_only else ""
        fq = f"&flag={_e(flag)}" if flag else ""
        res = await list_conversations_on(db, day, limit=per,
                                          offset=(page - 1) * per,
                                          source=source, day_to=to,
                                          needs_only=needs_only, flag=flag)
        rows = await attach_feedback(db, res["rows"])
        res["rows"] = rows
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

        # The flag bar carries the range and the source with it -- losing
        # them on a filter click is how a filtered view silently becomes an
        # unfiltered one.
        fcounts = res.get("flag_counts") or {}
        _carry = f"day={_e(day)}{rq}{sq}{nq}{kq}"
        flag_bar = " ".join(
            [f"<a class='tag{'' if flag else ' active'}' "
             f"href='/admin/conversations?{_carry}'>any</a>"]
            + [f"<a class='tag{' active' if t == flag else ''}' "
               f"href='/admin/conversations?{_carry}&flag={t}'>{_e(label)}"
               + (f" <span class='dim'>{fcounts[t]}</span>"
                  if fcounts.get(t) else "")
               + "</a>"
               for t, label in _FLAG_TAGS]
        )

        # GROUPED BY MONTH, AND FOLDED.
        #
        # A flat strip of every day with traffic was fourteen chips in
        # August and will be three hundred by next summer. `<details>`
        # rather than a script: it is native, keyboard-reachable, and it
        # survives the console being read with JavaScript off.
        #
        # The number is QUESTIONS, not conversations. The header above
        # this counts conversations, so the same day showed "3
        # conversation(s)" and a chip reading 11 with nothing saying they
        # measured different things. Reported 2026-08-31.
        by_month: "dict[str, list]" = {}
        for d in days:
            by_month.setdefault(d["day"][:7], []).append(d)

        def _month_block(month: str, rows: list, first: bool) -> str:
            asked = sum(r["questions"] for r in rows)
            chips = " ".join(
                f"<a class='tag{' active' if r['day'] == day else ''}' "
                f"href='/admin/conversations?day={_e(r['day'])}{kq}'>"
                f"{_e(r['day'][8:])} <span class='dim'>{r['questions']}"
                f"{'+' if r.get('partial') else ''}</span></a>"
                for r in rows)
            label = dt.date.fromisoformat(rows[0]["day"]).strftime("%B %Y")
            return (
                f"<details{' open' if first else ''}>"
                f"<summary>{_e(label)} "
                f"<span class='dim'>{len(rows)} day(s), {asked} question(s)"
                f"</span></summary>"
                f"<div class='filter-bar' style='margin:.5rem 0 .9rem'>"
                f"{chips}</div></details>")

        recent = "".join(
            _month_block(m, rows, i == 0)
            for i, (m, rows) in enumerate(sorted(by_month.items(),
                                                 reverse=True)))
        if any(r.get("partial") for d in days for r in [d]):
            recent += ("<p class='hint'>A count marked <code>+</code> is "
                       "short: that day sits at the edge of how far back "
                       "this reads.</p>")

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
            return HTMLResponse(ui.page("Conversations", body, who=caller,
                                        current="/admin/conversations", key=key))

        _SRC_CLASS = {"staff": "thumbs_up", "bot": "refusal",
                      # `local` is what "bot" was called before 2026-08-27.
                      # Rows written then still carry it, and losing the
                      # colour would make an old row look like a new kind
                      # of thing.
                      "local": "refusal",
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
            # B / S / P -- bot, staff, patron. They were S / T / P until
            # 2026-08-27, where "S" meant script-local and "T" meant staff:
            # the letters did not match their own words, and the reader had
            # to hover to find out which was which.
            controls = (
                "<span class='setsrcs'>"
                + set_link(cid, "bot", "B", "Mark as a bot / script — not a "
                                            "person")
                + set_link(cid, "staff", "S", "Mark as staff testing")
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
            # The patron's own verdict, which /admin/review showed inline and
            # this page did not. It is the only signal here that comes from
            # the person who was actually helped or not.
            # Numeric, not five glyphs: "2/5" is instantly a bad rating
            # and "★★" needs counting against a scale you have to assume.
            _stars = r.get("feedback_rating")
            if _stars:
                flags.append(f"<span class='tag' title='patron rating'>"
                             f"{int(_stars)}/5</span>")
            _cmt = (r.get("feedback_comment") or "").strip()
            if _cmt:
                flags.append(f"<span class='tag' title='{_e(_cmt)}'>"
                             f"💬 {_e(_cmt[:40])}"
                             f"{'…' if len(_cmt) > 40 else ''}</span>")
            for _in in (r.get("intents") or [])[:3]:
                flags.append(f"<span class='tag intent' title='what the bot "
                             f"classified this as'>{_e(_in)}</span>")
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

        # Range + "only what went wrong". Rendered as a form rather than
        # links because two dates and a checkbox is a form; the rest of the
        # page's filters are one click each and stay links.
        range_bar = (
            f"<form method='get' action='/admin/conversations' "
            f"class='rangebar' style='margin:.5rem 0;display:flex;gap:.4rem;"
            f"align-items:center;flex-wrap:wrap'>"
            + (f"<input type='hidden' name='key' value='{_e(key)}'>" if key else "")
            + (f"<input type='hidden' name='source' value='{_e(source)}'>"
               if source else "")
            + f"<label for='r-from' class='dim'>from</label>"
            f"<input id='r-from' type='date' name='day' value='{_e(day)}'>"
            f"<label for='r-to' class='dim'>to</label>"
            f"<input id='r-to' type='date' name='to' value='{_e(to)}' "
            f"placeholder='same day'>"
            f"<label class='dim'><input type='checkbox' name='needs' value='1'"
            f"{' checked' if needs_only else ''}> only what went wrong</label>"
            f"<button type='submit'>Show</button>"
            + (f" <a class='tag' href='/admin/conversations"
               f"{('?key=' + _e(key)) if key else ''}'>clear</a>"
               if (to or needs_only) else "")
            + f"</form>"
            + (f"<p class='dim'>Range clamped to {MAX_DAY_SPAN} days — the "
               f"whole span is read and grouped in memory, so a wider one "
               f"would be a scan nobody is waiting for.</p>"
               if res.get("clamped") else "")
        )

        needs_count = sum(1 for r in rows if r["needs_look"])
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
        # The way to the sweep, which had no way in at all.
        #
        # The sweep has existed for weeks and `reviewedAt` was null on all
        # 324 flagged rows -- not because nobody wanted it, but because no
        # page linked to it and you had to know the URL. It belongs where
        # the queue is, and it only appears when there is something to
        # sweep, so it is an offer rather than a permanent button.
        # NO NUMBER HERE ON PURPOSE.
        #
        # The obvious one to reach for is the source counts computed for
        # the bar above -- and they count CONVERSATIONS in the whole date
        # range, not flagged TURNS. It read "761 of these came from our own
        # testing" above a queue of 324. A wrong number on the way to a
        # right one is worse than no number, and the preview behind this
        # link states the real one because it does the real query.
        sweep = ""
        if flag:
            sweep = (
                f"<p class='hint' style='margin:-.5rem 0 1rem'>"
                f"Most of this queue is our own testing rather than a "
                f"patron's bad experience. "
                f"<a href='/admin/review/close-testing"
                f"{('?key=' + _e(key)) if key else ''}'>"
                f"See how many, and close them</a> — reversible, and "
                f"nothing is deleted.</p>")

        body = (
            f"<h1>Conversations</h1>"
            f"{search_box}"
            f"<div style='margin:.6rem 0'>{nav}</div>"
            f"<div class='filter-bar'>{source_bar}</div>"
            f"<div class='filter-bar'>{flag_bar}</div>"
            f"{sweep}"
            + (f"<p class='dim'>13 August is shown from 6:00pm, when the "
               f"bot went live to the public.</p>"
               if day == BETA_START_LOCAL[:10] else "")
            + range_bar
            + f"<p class='dim'>{total} conversation(s) "
            + ("in this range" if to else "on this day")
            + (" that something went wrong in" if needs_only else "")
            + (f" &middot; <b>{needs_count}</b> on this page worth a look"
               if needs_count and not needs_only else "")
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
            # Tokens, not hex. This block said `background:#fffaf5` and
            # `var(--miami)` -- names from the stylesheet as it stood
            # before 2026-08-30. The tint became a white block in dark
            # mode and the two variables became undefined, so the hover
            # simply stopped happening. Anything that paints has to come
            # from the shared tokens or it only works in one theme.
            + f"<style>.convs tr.needs td"
            f"{{background:hsl(var(--danger) / .09)}}"
            f".convs .setsrcs{{white-space:nowrap;margin-left:.35rem}}"
            f".convs .setsrc{{display:inline-block;width:1.15rem;"
            f"text-align:center;font-size:.7rem;line-height:1.15rem;"
            f"border:1px solid hsl(var(--border));border-radius:3px;"
            f"color:hsl(var(--muted-foreground));"
            f"text-decoration:none;margin-left:.1rem}}"
            f".convs .setsrc:hover{{background:hsl(var(--primary));"
            f"color:hsl(var(--primary-foreground));"
            f"border-color:hsl(var(--primary))}}"
            f".convs td.num{{text-align:right;white-space:nowrap;"
            f"font-variant-numeric:tabular-nums}}</style>"
            # "Flags" was a bare <th></th>. The column carries refusals,
            # thumbs, low confidence, the patron's rating and the classified
            # intent -- the densest column on the page and the only one a
            # reader had to infer the meaning of. An unlabelled header is
            # also unreachable to a screen reader.
            f"<table><tr><th>Time</th><th>Source</th><th>First question</th>"
            f"<th>Asked</th><th>Flags</th></tr>"
            + "".join(row(r) for r in rows) + "</table>"
            + pager()
            + f"<h2 style='font-size:.95rem;margin-top:1.4rem'>Other days</h2>"
            f"<p class='hint' style='margin:-.3rem 0 .6rem'>The number "
            f"beside each day is how many QUESTIONS were asked, which is "
            f"not the count of conversations above.</p>"
            f"<div>{recent}</div>"
        )
        return HTMLResponse(ui.page(
            "Conversations", f"<div class='convs'>{body}</div>",
            current="/admin/conversations", key=key, who=caller))


    @router.get("/admin/search", response_class=HTMLResponse)
    async def search(q: str = "", who: str = "any", key: str = "",
                     page: int = 1, per: int = 50,
                     caller=Depends(guard)) -> Any:
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
        return HTMLResponse(ui.page("Search", body, who=caller,
                                    current="/admin/conversations", key=key))

    @router.get("/admin/conversations/{conversation_id}/source",
                response_class=HTMLResponse)
    async def set_source(conversation_id: str, set: str = "", day: str = "",
                         key: str = "", source: str = "",
                         caller=Depends(guard)) -> Any:
        """Record, or clear, a person's verdict on one conversation.

        A GET from a link on the row it concerns. Reversible in one click,
        so it needs no confirmation step; making somebody confirm a label
        they can undo is how a correction stops being worth making.
        """
        from fastapi.responses import RedirectResponse

        from src.api.admin.review_queries import MANUAL_LABELS

        value = canonical_source(set or "")
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
