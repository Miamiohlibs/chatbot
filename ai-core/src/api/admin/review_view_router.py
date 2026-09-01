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
    BETA_START_LOCAL,
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
          who=None,
          counts: "Any" = None) -> str:
    return ui.page(title, body, current=current, key=key,
                   counts=counts, who=who)


TAG_WHY = {
    "bot": "a replay, or every question in it was asked first by somebody else",
    "staff": "arrived through the staff-test link, or carries a staff address",
    "local": "the old name for `bot`, on rows written before 2026-08-27",
    "maybe-staff": "INFERRED from pace or repetition — not recorded",
}


def build_review_view_router(deps: dict) -> Any:
    """`deps` = {"db": prisma, "guard": token-dependency}."""
    try:
        from fastapi import APIRouter, Depends  # type: ignore
        from fastapi.responses import (  # type: ignore
            HTMLResponse,
            RedirectResponse,
        )
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
        who=Depends(guard),
    ) -> Any:
        """Redirect to the conversations view, which now does this.

        Flagged listed MESSAGES matching a preset and dropped them once
        marked handled. The conversations view could not do either -- until
        it grew a date range, a "only what went wrong" filter, the same
        flag presets and the patron's rating inline. What is left of the
        difference is the mark-handled queue, and NOBODY EVER USED IT:
        reviewedAt is null on all 3,096 assistant messages ever logged,
        which is why 318 rows sat in a queue that never shrank.

        Kept as a redirect rather than deleted: this URL is in browser
        history, in bookmarks, and in the hub cards of anyone who has the
        page open. A 404 would read as the console being broken.

        /admin/review/{conversation_id} is NOT affected -- that is the
        transcript view, and tickets, search and every list link into it.
        """
        _map = {
            "refusal": "refusal",
            "thumbs_down": "thumbs_down",
            "thumbs_up": "thumbs_up",
            "low_confidence": "low_confidence",
        }
        params = []
        if key:
            params.append(f"key={_e(key)}")
        if filter in _map:
            params.append(f"flag={_map[filter]}")
        elif filter not in ("all", "reviewed", "rated"):
            # "flagged" -- the default preset -- is the union of the three
            # bad signals, which is exactly what needs=1 means here.
            params.append("needs=1")
        # A preset spanning all time becomes a range ending today; the
        # conversations view is day-anchored and would otherwise land on
        # today alone and look empty by comparison.
        # Imported here, not at module scope: conversations_router imports
        # from this package too, and a top-level import between the two
        # closes the cycle.
        from src.api.admin.conversations_router import today_local

        params.append(f"day={_e(BETA_START_LOCAL[:10])}")
        params.append(f"to={_e(today_local())}")
        target = "/admin/conversations?" + "&".join(params)
        return RedirectResponse(target, status_code=307)

    @router.get("/admin/review/close-testing", response_class=HTMLResponse)
    async def close_testing_preview(key: str = "", who=Depends(guard)) -> Any:
        """What a sweep would close, BEFORE it closes anything.

        This used to close on the GET. The docstring's defence was that
        the operator had just read the count on the link they clicked --
        except no page linked here at all, so the count they had read was
        nothing. `reviewedAt` was null on all 324 rows: the sweep existed
        for weeks and had never once been run, because there was no way to
        reach it. Same fault the kill switch had until 2026-08-08.

        Two steps now. A GET that changes 312 rows is the wrong shape
        whatever links to it.
        """
        r = await close_testing_rows(db, dry_run=True, by="operator")
        kq = _kq_plain(key)
        by = r["by_tag"] or {}
        rows = "".join(
            f"<tr><td><code>{_e(t)}</code></td><td>{_e(n)}</td>"
            f"<td>{_e(TAG_WHY.get(t, ''))}</td></tr>"
            for t, n in sorted(by.items(), key=lambda kv: -kv[1]))
        guess = by.get("maybe-staff", 0)
        caveat = ""
        if guess:
            caveat = (
                f"<p class='warn'><b>{guess} of these are a guess.</b> "
                f"<code>maybe-staff</code> is inferred from the pace and "
                f"shape of a conversation, not recorded at the door. If the "
                f"inference is wrong, a real patron's bad experience gets "
                f"closed. Closing is reversible and these stay on the "
                f"<b>reviewed</b> tab, so this is a judgement about how much "
                f"reading you want to do, not a one-way door.</p>")
        return HTMLResponse(_page(
            "Sweep the queue",
            f"<h1>Close {r['closed']} flagged turn(s) from our own testing"
            f"</h1>"
            f"<p class='lede'>A flagged turn says \"a patron may have had a "
            f"bad experience here\". A turn from our own scripted run says "
            f"nothing of the kind, and it buries the ones that do.</p>"
            f"<div class='scroll-table'><table><thead><tr><th>Source</th>"
            f"<th>Turns</th><th>Why we know</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div>"
            f"{caveat}"
            f"<p><b>{r['kept']}</b> turn(s) stay in the queue — everything "
            f"we cannot attribute to ourselves"
            + (f", <b>including {r['rated_down']} that somebody pressed "
               f"thumbs-down on</b>. Those are never swept, whoever pressed "
               f"the button: attribution answers whether a PATRON had a bad "
               f"experience, and a thumbs-down answers whether the ANSWER "
               f"was bad. The second question does not care who asked it."
               if r.get("rated_down") else ".") + "</p>"
            f"<p class='hint'>Nothing is deleted. Closing sets a reviewed "
            f"date; the rows stay on the <b>reviewed</b> tab and un-marking "
            f"one is a click.</p>"
            f"<form method='post' action='/admin/review/close-testing{kq}'>"
            f"<div class='acts'>"
            f"<button type='submit'>Close {r['closed']} testing turn(s)"
            f"</button>"
            f"{ui.action('/admin/conversations' + kq, 'Not now', ghost=True)}"
            f"</div></form>",
            current="/admin/conversations", key=key, who=who))

    @router.post("/admin/review/close-testing", response_class=HTMLResponse)
    async def close_testing(key: str = "", who=Depends(guard)) -> Any:
        result = await close_testing_rows(db, dry_run=False, by="operator")
        logger.info("closed %d flagged rows from testing (%s), kept %d",
                    result["closed"], result["by_tag"], result["kept"])
        back = "/admin/conversations" + _kq_plain(key)
        return HTMLResponse(_page(
            "Queue swept",
            f"<h1>Closed {result['closed']} flagged turn(s)</h1>"
            f"<p class='lede'>They came from our own testing, so they were "
            f"never reports of a patron's bad experience. "
            f"<b>{result['kept']}</b> stayed in the queue.</p>"
            f"<p class='hint'>Nothing was deleted. Everything closed here is "
            f"still on the <b>reviewed</b> tab, and marking a row reviewed "
            f"is reversible.</p>"
            f"<div class='acts'>{ui.action(back, '← back to the queue', primary=True)}"
            "</div>",
            current="/admin/conversations", key=key, who=who))

    @router.get("/admin/review/mark/{message_id}", response_class=HTMLResponse)
    async def review_mark(
        message_id: str,
        filter: str = "flagged",
        key: str = "",
        undo: int = 0,
        who=Depends(guard),
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
        who=Depends(guard),
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

            # THE IDS ONLY. The text is looked up on the other side.
            #
            # This carried up to 1,000 characters of the patron's question
            # and 2,000 of the answer in the query string, which is to say
            # in nginx's access log, in browser history, and in the Referer
            # of anything that page links out to. A patron's typing is the
            # single field here most likely to contain something personal,
            # and it has been an incident on this project before.
            #
            # `message_id` fetches both at the far end, so the form still
            # opens filled in and nothing is retyped. `prev_user` is kept
            # in the signature because the caller computes it anyway and
            # the next reader will wonder where the question went.
            del prev_user
            qs = urlencode({
                "key": lib_code,
                "conversation_id": conversation_id,
                "message_id": m.get("id") or "",
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
