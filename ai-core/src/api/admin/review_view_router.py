"""
Server-rendered, zero-dependency HTML review surface (plan Op 1 MVP).

The plan's Op 1 MVP is explicitly "Metabase/Retool + saved queries"
before a custom React SPA. We don't have Metabase to stand up, and a
React admin app is large + can't be verified offline -- so this is
the equivalent with NO new infra: two FastAPI routes returning plain
HTML that read the existing tables via review_queries. A librarian
opens a bookmarked link, sees the flagged conversations, clicks one,
reads id / time / full transcript / token usage / tools / handoff /
outcome, and reports the id+time to the maintainer.

SECURITY (this exposes raw conversation logs = user input + PII):
  * `make_token_guard`: fail-CLOSED. Requires the ADMIN_API_TOKEN
    secret via `X-Admin-Token` header OR `?key=` query param (the
    query param lets a librarian use a bookmarked browser link).
    main.py mounts the whole admin surface ONLY when ADMIN_API_TOKEN
    is set, so a misconfigured deploy can't leak conversation logs.
  * Every interpolated value is html.escape()'d. Conversation content
    is attacker-controllable user text rendered in the librarian's
    browser -- unescaped it would be stored XSS against staff.
"""

from __future__ import annotations

import html
from typing import Any

import logging

from src.api.admin import admin_ui as ui

logger = logging.getLogger(__name__)
from src.api.admin.review_queries import (
    close_testing_rows,
    count_flagged,
    FILTERS,
    dashboard_counts,
    attach_feedback,
    conversation_detail,
    list_flagged,
    mark_reviewed,
)

# Module-level so FastAPI/Starlette can resolve the `request: Request`
# annotation on the guard + handlers (it resolves annotations against
# THIS module's globals -- a function-local import is invisible to it
# and FastAPI then mis-treats `request` as a query param). starlette is
# always installed alongside fastapi; Any fallback keeps the module
# importable in a no-fastapi sandbox (router returns a placeholder
# there anyway).
try:
    from starlette.requests import Request  # type: ignore
except Exception:  # noqa: BLE001
    Request = Any  # type: ignore


def make_token_guard(expected_token: str):
    """FastAPI dependency: 401 unless the request carries the admin
    token. Fail-closed (empty expected_token -> always 401)."""
    from fastapi import HTTPException  # type: ignore

    async def guard(request: Request) -> None:
        supplied = (
            request.headers.get("x-admin-token")
            or request.query_params.get("key")
            or ""
        )
        if not expected_token or supplied != expected_token:
            raise HTTPException(status_code=401, detail="admin auth required")

    return guard


# Presentation comes from the shared admin UI module so every operator
# surface looks like one tool (redesign 2026-07-28 -- five pages had
# grown five stylesheets).
_e = ui.e


def _kq_plain(key: str) -> str:
    return f"key={_e(key)}" if key else ""


def _page(title: str, body: str, *, current: str = "", key: str = "",
          counts: "Any" = None) -> str:
    return ui.page(title, body, current=current, key=key, counts=counts)


def build_review_view_router(deps: dict) -> Any:
    """`deps` = {"db": prisma, "guard": token-dependency}."""
    try:
        from fastapi import APIRouter, Depends  # type: ignore
        from fastapi.responses import HTMLResponse  # type: ignore
    except ImportError:
        class _P:
            prefix = "/admin/review"
            routes: list = []
        return _P()

    router = APIRouter(tags=["admin"])
    db = deps["db"]
    guard = deps["guard"]

    # The librarian ticket form is gated by its own shared code, so the
    # "Report this answer" link has to carry it. That is not an escalation:
    # this page is already behind the admin guard, and anyone who can read
    # it can take the bot out of service, write corrections and read every
    # conversation held. The ticket code buys only the right to file a
    # ticket. Read at request time, not import time, so setting it does not
    # need a restart -- and when it is unset the link simply does not
    # render rather than producing a 401 the operator cannot explain.
    import os as _os

    def _librarian_code() -> str:
        return (deps.get("librarian_code")
                or _os.getenv("LIBRARIAN_TICKET_CODE", "")).strip()

    @router.get("/admin/review", response_class=HTMLResponse)
    async def review_list(
        filter: str = "flagged",
        page: int = 1,
        per: int = 50,
        limit: int = 50,
        key: str = "",
        _g=Depends(guard),
    ) -> Any:
        counts = await dashboard_counts(db)
        page, per, offset = ui.page_bounds(page, per)
        rows = await list_flagged(db, filter_preset=filter, limit=per,
                                  offset=offset)
        total = await count_flagged(db, filter_preset=filter)
        # Patron star ratings live on the conversation, so project them
        # onto the message rows -- otherwise "who rated us" is invisible
        # from the list (operator report 2026-07-27).
        rows = await attach_feedback(db, rows)
        _kq = ("&key=" + _e(key)) if key else ""
        _filter_class = {
            "flagged": "flagged",
            "thumbs_down": "down",
            "thumbs_up": "up",
            "refusal": "refuse",
            "low_confidence": "low-conf",
            "rated": "rated",
            "reviewed": "done",
            "all": "all",
        }
        opts = "".join(
            f"<a class='tag {_filter_class.get(f, f)}"
            f"{' active' if f == filter else ''}'"
            f" href='/admin/review?filter={f}{_kq}'>{_e(f)}</a>"
            for f in FILTERS
        )
        trs = []
        for r in rows:
            cid = r.get("conversation_id") or ""
            mid = r.get("message_id") or ""
            flags = []
            # The classifier's verdict, first, so the row reads "the bot
            # took this as X -- and here is what went wrong with it". It
            # was recorded on every turn already (1,204 of 1,204 August
            # assistant messages carry one) and simply never shown, so
            # working the queue meant opening a conversation to find out
            # what the bot thought it was being asked.
            if r.get("intent"):
                scope_bits = " / ".join(
                    x for x in (r.get("scope_campus"), r.get("scope_library"))
                    if x
                )
                title = f"classified intent{f' — scope {scope_bits}' if scope_bits else ''}"
                flags.append(
                    f"<span class='tag intent' title='{_e(title)}'>"
                    f"{_e(r.get('intent'))}</span>")
            if r.get("is_positive_rated") is False:
                flags.append("<span class='tag down'>&#128078; thumbs-down</span>")
            elif r.get("is_positive_rated") is True:
                flags.append("<span class='tag up'>&#128077; thumbs-up</span>")
            if r.get("was_refusal"):
                flags.append(
                    f"<span class='tag refuse'>refusal:"
                    f"{_e(r.get('refusal_trigger'))}</span>")
            if r.get("confidence") == "low":
                flags.append("<span class='tag low-conf'>low-conf</span>")
            fr = r.get("feedback_rating")
            if fr is not None:
                stars = "&#9733;" * max(0, min(int(fr), 5))
                cmt = (r.get("feedback_comment") or "").strip()
                flags.append(
                    f"<span class='tag rated' title='{_e(cmt)}'>"
                    f"{stars} {_e(str(fr))}/5"
                    f"{' &#128172;' if cmt else ''}</span>")
            if r.get("reviewed_at"):
                flags.append("<span class='tag done'>reviewed</span>")
            link = f"/admin/review/{_e(cid)}" + (f"?key={_e(key)}" if key else "")
            # Triage action, inline so the queue can be worked from the
            # list. Returns to the current filter view.
            act_label, act_q = (
                ("undo", "&undo=1") if r.get("reviewed_at")
                else ("mark reviewed", "")
            )
            act = (
                f"<a class='act' href='/admin/review/mark/{_e(mid)}"
                f"?filter={_e(filter)}{_kq}{act_q}'>{act_label}</a>"
                if mid else ""
            )
            cmt_row = (
                f"<br><small class='cmt'>&#128172; "
                f"{_e((r.get('feedback_comment') or '')[:160])}</small>"
                if (r.get("feedback_comment") or "").strip() else ""
            )
            trs.append(
                f"<tr><td>{_e(r.get('time'))}</td>"
                f"<td>{_e(r.get('role'))}</td>"
                f"<td>{_e(r.get('preview'))}{cmt_row}</td>"
                f"<td>{' '.join(flags)}</td>"
                f"<td><a href='{link}'>view</a><br>{act}<br>"
                f"<small>{_e(cid)}</small></td></tr>"
            )
        _scope_note = (
            "" if filter in ("reviewed", "all")
            else " &mdash; unreviewed only"
        )
        _pager = ui.pager("/admin/review", page=page, per=per, total=total,
                          key=key, extra=f"&filter={_e(filter)}")

        # How much of this queue is our own testing. Shown before anything
        # is closed, because a bulk write the operator cannot see the shape
        # of first is a bulk write they cannot judge.
        sweep = ""
        if filter == "flagged" and total:
            preview = await close_testing_rows(db, dry_run=True)
            if preview["closed"]:
                bits = ", ".join(f"{n} {t.replace('-', ' ')}"
                                 for t, n in sorted(preview["by_tag"].items()))
                sweep = (
                    f"<div class='note' style='margin:.8rem 0'>"
                    f"<b>{preview['closed']} of these {total} came from "
                    f"testing</b> ({bits}). A flagged turn is meant to say a "
                    f"patron may have had a bad experience; one from our own "
                    f"scripted run says nothing of the kind, and leaving them "
                    f"here buries the {preview['kept']} that might be real."
                    f"<div class='acts' style='margin-top:.6rem'>"
                    + ui.action(
                        f"/admin/review/close-testing?{_kq_plain(key)}",
                        f"Close all {preview['closed']}", primary=True)
                    + "</div></div>"
                )
        body = (
            f"<h1>Flagged conversations</h1>"
            f"<p class='lede'>{total} row(s) &middot; filter: "
            f"{_e(filter)}{_scope_note}. Patron star ratings and comments "
            f"show inline; marking a row reviewed drops it out of the "
            f"working views.</p><div class='filter-bar'>{opts}</div>"
            f"{sweep}{_pager}"
            f"<table><tr><th>time</th><th>role</th><th>preview</th>"
            f"<th>flags</th><th>conversation</th></tr>"
            f"{''.join(trs) or '<tr><td colspan=5>none</td></tr>'}"
            f"</table>{_pager}"
        )
        return HTMLResponse(_page("Flagged conversations", body,
                                  current="/admin/review", key=key,
                                  counts=counts))

    @router.get("/admin/review/close-testing", response_class=HTMLResponse)
    async def close_testing(key: str = "", _g=Depends(guard)) -> Any:
        """Close every flagged turn that came from testing.

        A GET because it is reached from a link the operator has just read
        the count on, and it is reversible: closing a row sets reviewedAt,
        and the `reviewed` tab still shows it.
        """
        result = await close_testing_rows(db, dry_run=False, by="operator")
        logger.info("closed %d flagged rows from testing (%s), kept %d",
                    result["closed"], result["by_tag"], result["kept"])
        back = "/admin/review" + (f"?key={_e(key)}" if key else "")
        return HTMLResponse(_page(
            "Queue swept",
            f"<h1>Closed {result['closed']} flagged turn(s)</h1>"
            f"<p class='lede'>They came from our own testing, so they were "
            f"never reports of a patron's bad experience. "
            f"<b>{result['kept']}</b> stayed in the queue.</p>"
            f"<p class='dim'>Nothing was deleted. Everything closed here is "
            f"still on the <b>reviewed</b> tab, and marking a row reviewed "
            f"is reversible.</p>"
            f"<div class='acts'>{ui.action(back, '← back to the queue', primary=True)}"
            f"{ui.action(back + ('&' if key else '?') + 'filter=reviewed', 'See what was closed', ghost=True)}"
            f"</div>",
            current="/admin/review", key=key))

    @router.get("/admin/review/mark/{message_id}", response_class=HTMLResponse)
    async def review_mark(
        message_id: str,
        filter: str = "flagged",
        key: str = "",
        undo: int = 0,
        _g=Depends(guard),
    ) -> Any:
        """Flip one row's triage state, then bounce back to the list.

        GET (not POST) so it works as a plain link in this
        dependency-free HTML surface, same as the ticket queue's status
        links. The action is idempotent and reversible via `undo`.
        """
        await mark_reviewed(db, message_id, undo=bool(undo))
        back = f"/admin/review?filter={_e(filter)}" + (
            f"&key={_e(key)}" if key else "")
        return HTMLResponse(
            f"<!doctype html><meta charset='utf-8'>"
            f"<meta http-equiv='refresh' content='0;url={back}'>ok"
        )

    @router.get("/admin/review/{conversation_id}",
                response_class=HTMLResponse)
    async def review_detail(
        conversation_id: str,
        key: str = "",
        _g=Depends(guard),
    ) -> Any:
        d = await conversation_detail(db, conversation_id)
        lib_code = _librarian_code()
        back = "/admin/review" + (f"?key={_e(key)}" if key else "")
        if d is None:
            return HTMLResponse(
                _page("Not found",
                      f"<p>conversation not found.</p>"
                      f"<a href='{back}'>&larr; back</a>"),
                status_code=404,
            )
        kq = f"?key={_e(key)}" if key else "?"

        def _sources(m: dict) -> str:
            """The passages the bot answered from, each with a one-click
            handoff to the tool that fixes it.

            Added 2026-08-08. `suppress` and `replace` corrections are
            keyed by chunk id, and no operator surface displayed a chunk
            id anywhere -- so two of the four correction types could not
            be filed from the console at all without going to the
            database for the id.
            """
            ids = m.get("cited_chunk_ids") or []
            if not ids:
                return ""
            sep = "&" if key else ""
            items = "".join(
                f"<li><code>{_e(cid)}</code> "
                f"<a class='btn ghost' href='/admin/corrections/view{kq}{sep}"
                f"action=suppress&target={_e(cid)}'>hide it</a> "
                f"<a class='btn ghost' href='/admin/corrections/view{kq}{sep}"
                f"action=replace&target={_e(cid)}'>reword it</a></li>"
                for cid in ids
            )
            return ("<div><small class='dim'>Passages this answer came "
                    f"from</small><ul class='sources'>{items}</ul></div>")

        def _links(m: dict) -> str:
            """The URLs the patron was actually shown, in citation order.

            Added 2026-08-16 at the operator's request. `_sources` above
            shows CHUNK IDS, which exist only for retrieval-built answers --
            measured that day, 401 of 1,872 assistant messages had them. For
            the other 79%, all of them deterministic short-circuits carrying
            hand-verified URLs, the console showed nothing at all about where
            we had sent the patron.

            Numbered [1], [2] to match the markers in the answer text above,
            so a reviewer reading "see the reserves guide [1]" can see what
            [1] resolved to without leaving the page. Rendered as real links
            so a wrong or dead one can be checked in a click -- that is the
            point of showing them.
            """
            urls = m.get("cited_urls") or []
            if not urls:
                return ""
            items = "".join(
                f"<li>[{i}] <a href='{_e(u)}' target='_blank' "
                f"rel='noopener noreferrer'>{_e(u)}</a></li>"
                for i, u in enumerate(urls, 1)
            )
            return ("<div><small class='dim'>Links shown to the patron"
                    f"</small><ol class='sources'>{items}</ol></div>")

        def _turn_badges(m: dict) -> str:
            """What the bot DECIDED about this turn, before what went wrong.

            intent, scope, confidence and model are recorded on every
            assistant message -- 1,204 of 1,204 in August carry all four --
            and none of them were ever rendered, so answering "why did it
            say that" meant reading the transcript and guessing which
            branch it took.
            """
            if m.get("role") != "assistant":
                return ""
            out = []
            if m.get("intent"):
                out.append(f"<span class='tag intent' title='classified "
                           f"intent'>{_e(m['intent'])}</span>")
            scope_bits = " / ".join(
                x for x in (m.get("scope_campus"), m.get("scope_library")) if x)
            if scope_bits:
                out.append(f"<span class='tag all' title='resolved scope'>"
                           f"{_e(scope_bits)}</span>")
            if m.get("confidence"):
                cls = "low-conf" if m["confidence"] == "low" else "all"
                out.append(f"<span class='tag {cls}' title='synthesizer "
                           f"confidence'>{_e(m['confidence'])}</span>")
            if m.get("model_used"):
                # "(none -- <path>_short_circuit)" means no LLM ran at all,
                # so the tooltip must not call it the model that answered.
                _mu = str(m["model_used"])
                _title = ("answered deterministically -- no model call"
                          if _mu.startswith("(none")
                          else "model that answered")
                out.append(f"<span class='tag all' title='{_title}'>"
                           f"{_e(_mu)}</span>")
            return "".join(out)

        def _report_link(m: dict, prev_user: str) -> str:
            """One click from a wrong answer to a ticket that points back.

            Until 2026-08-27 a ticket carried only the librarian's typed
            copy of the question and the answer, and the ticket page had to
            GUESS which conversation it came from by matching that typing
            against every question ever asked -- finding nothing whenever
            they paraphrased, and the wrong conversation when two patrons
            typed the same sentence. One ticket exists in the table, which
            is what a path nobody can walk looks like.

            Prefills what is already on screen and carries the ids, so the
            link is recorded rather than reconstructed.
            """
            if m.get("role") != "assistant":
                return ""
            from urllib.parse import urlencode

            qs = urlencode({
                "key": lib_code,
                "conversation_id": conversation_id,
                "message_id": m.get("id") or "",
                "question": (prev_user or "")[:1000],
                "bot_answer": (m.get("content") or "")[:2000],
            })
            return (f"<a class='btn ghost' href='/librarian/ticket?{qs}' "
                    f"target='_blank' rel='noopener'>Report this answer</a>")

        # The patron line each assistant turn is answering, so the report
        # form can prefill the question without the librarian retyping it.
        _prev_user: list = []
        _last = ""
        for _m in d["messages"]:
            _prev_user.append(_last)
            if _m.get("role") == "user":
                _last = _m.get("content") or ""

        msgs = "".join(
            f"<div class='msg'>"
            f"<div class='msg-hd'>"
            f"<span class='role'>{_e(m['role'])}</span>"
            f"<small class='time'>{_e(m['time'])}</small>"
            + _turn_badges(m)
            + ("<span class='tag refuse'>refusal: "
               f"{_e(m['refusal_trigger'])}</span>" if m['was_refusal']
               else "")
            + ("<span class='tag down'>thumbs-down</span>"
               if m['is_positive_rated'] is False else "")
            + f"</div><pre>{_e(m['content'])}</pre>{_links(m)}{_sources(m)}"
            + (f"<div class='acts'>{_report_link(m, pu)}</div>"
               if lib_code else "")
            + "</div>"
            for m, pu in zip(d["messages"], _prev_user)
        )
        toks = "".join(
            f"<tr><td>{_e(t['model'])}</td><td>{_e(t['call_site'])}</td>"
            f"<td>{_e(t['prompt'])}</td><td>{_e(t['cached_input'])}</td>"
            f"<td>{_e(t['completion'])}</td><td>{_e(t['total'])}</td></tr>"
            for t in d["token_usage"]
        ) or "<tr><td colspan=6>none</td></tr>"
        tools = "".join(
            f"<tr><td>{_e(t['agent'])}</td><td>{_e(t['tool'])}</td>"
            f"<td>{_e(t['success'])}</td><td>{_e(t['ms'])}ms</td>"
            f"<td>{_e(t['time'])}</td></tr>"
            for t in d["tools_called"]
        ) or "<tr><td colspan=5>none</td></tr>"
        tsummary = ", ".join(_e(t) for t in (d.get("tools_used_summary") or [])) or "none"
        ho = ", ".join(
            f"{_e(h['trigger'])} @ {_e(h['time'])}"
            for h in d["human_handoff"]
        ) or "none"
        o = d["outcome"]
        fb = d["feedback"]
        body = (
            f"<p><a href='{back}'>&larr; back to queue</a></p>"
            f"<h2>Conversation {_e(d['conversation_id'])}</h2>"
            f"<p><b>created:</b> {_e(d['created_at'])} &nbsp; "
            f"<b>updated:</b> {_e(d['updated_at'])} &nbsp; "
            f"<b>token total:</b> {_e(d['token_total'])} &nbsp; "
            f"<b>human-handoff:</b> {ho}</p>"
            f"<p><b>outcome:</b> refusal={_e(o['was_refusal'])} "
            f"trigger={_e(o['refusal_trigger'])} "
            f"confidence={_e(o['confidence'])} &nbsp; "
            f"<b>feedback:</b> "
            + (f"rating={_e(fb['rating'])} note={_e(fb['comment'])}"
               if fb else "none")
            + f"</p><h3>Transcript</h3>{msgs}"
            f"<h3>Token usage</h3>"
            f"<div class='scroll-table'><table><tr><th>model</th>"
            f"<th>call_site</th><th>prompt</th><th>cached</th>"
            f"<th>completion</th><th>total</th></tr>{toks}</table></div>"
            f"<h3>Tools called</h3>"
            f"<p><b>Tools used:</b> {tsummary}</p>"
            f"<div class='scroll-table'><table><tr><th>agent</th>"
            f"<th>tool</th><th>ok</th><th>ms</th><th>time</th></tr>"
            f"{tools}</table></div>"
        )
        # key= was missing here, which made every tab in the top menu a
        # dead link on the page an operator lands on most -- you arrive from
        # Flagged or Conversations, and the only way back out was the
        # browser. Until SSO is on, the key IS the session.
        return HTMLResponse(_page(f"Conversation {conversation_id}", body,
                                  current="/admin/review", key=key))

    return router


__all__ = ["build_review_view_router", "make_token_guard"]
