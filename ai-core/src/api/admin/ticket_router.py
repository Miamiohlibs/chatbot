"""
Librarian correction tickets -- "the bot answered this wrong" reports.

Why: librarians who spot a wrong answer had no channel to report it
(operator request 2026-07-16). This gives them a bookmarkable form;
every submission is stored in Postgres (CorrectionTicket) AND emailed
to the operator via src/observability/alerting.py, so nothing depends
on the operator polling a dashboard.

Surfaces:
  GET  /librarian/ticket        -- the submission form (librarian-facing)
  POST /librarian/ticket        -- submit; stores + emails; confirmation page
  GET  /admin/tickets/view      -- operator list, newest first (admin token)
  GET  /admin/tickets/{id}/mark -- flip status open->reviewed->done (admin token)

SECURITY:
  * The librarian surface is gated by LIBRARIAN_TICKET_CODE (a shared
    access code the operator distributes to library staff). Fail-closed:
    main.py mounts it only when the code is set, and the guard 401s on
    a missing/wrong code. The code rides `?key=` so the form can be a
    browser bookmark -- same pattern as the admin token guard.
  * The admin list is behind the existing ADMIN_API_TOKEN guard.
  * Every interpolated value is html.escape()'d -- ticket content is
    staff-typed but may quote attacker-influenced bot output.
  * The email send NEVER blocks ticket creation: the row is written
    first; a failed email is recorded as emailSent=false and shows up
    in the admin list so it can't get lost silently.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

# Module level, NOT inside the factory. `from __future__ import annotations`
# above turns annotations into strings, and FastAPI resolves a handler's
# annotations against MODULE globals -- a Request imported inside the
# factory is invisible there and the parameter is read as a request body,
# which is a 422 on every POST. That shipped twice on 2026-08-21; this is
# the third place it would have.
try:  # pragma: no cover - FastAPI is always present in production
    from fastapi import Request
    from fastapi.responses import RedirectResponse
except ImportError:  # pragma: no cover
    Request = object  # type: ignore[assignment,misc]
    RedirectResponse = None  # type: ignore[assignment]

from src.api.admin import admin_ui as ui
from src.api.admin.review_queries import (
    conversation_detail,
    find_asks_like,
    local_ts,
)

try:
    from starlette.requests import Request  # type: ignore
except Exception:  # noqa: BLE001 -- keep importable in a no-fastapi sandbox
    Request = Any  # type: ignore

logger = logging.getLogger("ticket_router")


def key_present(request) -> bool:
    return bool(request.query_params.get("key"))

_MAX_FIELD = 8000  # hard cap per field; keeps a paste-bomb out of the DB

_FORM_FIELDS = (
    # (form name, label, required, textarea?)
    ("librarian_name", "Your name", True, False),
    ("librarian_email", "Your Miami email", True, False),
    ("question", "What the patron asked", True, True),
    ("bot_answer", "What the chatbot answered (paste it)", True, True),
    ("expected_answer", "What it SHOULD say / where the correct info lives", True, True),
    ("source_url", "Supporting URL (optional)", False, False),
)


def validate_ticket(form: dict) -> tuple[dict, list[str]]:
    """Pure validation: returns (clean_values, errors). No I/O."""
    clean: dict = {}
    errors: list[str] = []
    for name, label, required, _ta in _FORM_FIELDS:
        val = str(form.get(name) or "").strip()
        if len(val) > _MAX_FIELD:
            val = val[:_MAX_FIELD]
        if required and not val:
            errors.append(f"“{label}” is required.")
        clean[name] = val
    email = clean.get("librarian_email", "")
    if email and ("@" not in email or " " in email):
        errors.append("Please give a valid email address.")
    url = clean.get("source_url", "")
    if url and not url.lower().startswith(("http://", "https://")):
        errors.append("The supporting URL must start with http:// or https://.")
    return clean, errors


def ticket_email_body(t: dict) -> str:
    """Plain-text operator email for one ticket. Pure."""
    return (
        f"New chatbot correction ticket ({t.get('id', '?')})\n"
        f"From: {t.get('librarian_name')} <{t.get('librarian_email')}>\n"
        f"\n"
        f"PATRON ASKED:\n{t.get('question')}\n"
        f"\n"
        f"BOT ANSWERED:\n{t.get('bot_answer')}\n"
        f"\n"
        f"SHOULD BE:\n{t.get('expected_answer')}\n"
        f"\n"
        f"Supporting URL: {t.get('source_url') or '(none)'}\n"
        f"\n"
        f"Review queue: /admin/tickets/view\n"
    )


# --- HTML rendering (zero-dependency, same approach as review_view) -------

def render_form(key: str, values: dict | None = None,
                errors: list[str] | None = None) -> str:
    v = values or {}
    err_html = ""
    if errors:
        items = "".join(f"<li>{ui.e(x)}</li>" for x in errors)
        err_html = (f"<div class='card attn'><b>Please fix:</b>"
                    f"<ul>{items}</ul></div>")
    rows = []
    for name, label, required, textarea in _FORM_FIELDS:
        val = ui.e(v.get(name, ""))
        req = " *" if required else ""
        rows.append(f"<label for='{name}'>{ui.e(label)}{req}</label>")
        if textarea:
            rows.append(f"<textarea id='{name}' name='{name}'>{val}</textarea>")
        else:
            rows.append(
                f"<input type='text' id='{name}' name='{name}' value='{val}'>")
    body = (
        "<h1>Report a wrong chatbot answer</h1>"
        "<p class='lede'>Spotted the Smart Chatbot giving a wrong or "
        "outdated answer? Describe it below &mdash; the report goes straight "
        "to the maintainer (<a href='mailto:qum@miamioh.edu'>qum@miamioh.edu"
        "</a>).</p>"
        f"{err_html}"
        "<div class='card'><form method='post'>"
        f"<input type='hidden' name='key' value='{ui.e(key)}'>"
        f"{''.join(rows)}"
        "<div style='margin-top:1.2rem'>"
        "<button type='submit'>Submit report</button></div>"
        "</form></div>"
    )
    return _staff_page("Report a wrong answer", body)


def render_thanks(ticket_id: str, email_sent: bool, key: str) -> str:
    mail_note = (
        "The maintainer has been emailed."
        if email_sent else
        "The report is saved; the email notification could not be sent "
        "right now, but the maintainer will still see it in the queue."
    )
    body = (
        "<h1>Thank you!</h1>"
        f"<div class='card'><p>Your report was received "
        f"(id <code>{ui.e(ticket_id)}</code>). {ui.e(mail_note)}</p>"
        f"<div class='acts'>"
        f"{ui.action('/librarian/ticket?key=' + ui.e(key), 'Report another', primary=True)}"
        f"{ui.action('/librarian/?key=' + ui.e(key), 'Back to staff hub')}"
        f"</div></div>"
    )
    return _staff_page("Report received", body)


def _staff_page(title: str, body: str) -> str:
    """Staff pages share the visual language but NOT the operator nav --
    library staff must never see links into the admin console."""
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{ui.e(title)} — Miami University Libraries</title>"
        f"<style>{ui.STYLE}</style></head><body>"
        "<header class='top'><div class='wrap'><b>Smart Chatbot</b>"
        "<span style='opacity:.85'>library staff</span></div></header>"
        f"<main>{body}</main></body></html>"
    )


# Explicit states, explicit transitions. This used to be a single
# "mark <next>" link cycling open -> reviewed -> done -> OPEN, so a
# finished ticket silently reopened on an extra click and there was no
# way to jump straight to done (operator: "the handoffs are muddled",
# 2026-07-28). Now every transition is its own button.
VALID_STATUSES = ("open", "in_progress", "done")
_LEGACY_STATUS = {"reviewed": "in_progress"}


def normalize_status(status: object) -> str:
    """Map stored values (incl. the legacy 'reviewed') onto the current
    three. Unknown values fall back to open so a row is never stranded
    in a state the UI can't act on."""
    s = str(status or "open").strip().lower()
    s = _LEGACY_STATUS.get(s, s)
    return s if s in VALID_STATUSES else "open"


def _q(text: str) -> str:
    """URL-encode a short status message for the redirect back."""
    from urllib.parse import quote
    return quote(str(text)[:200], safe="")


def _default_expiry():
    from src.api.admin.corrections_router import default_expiry
    return default_expiry()


def _bust_serving_cache() -> None:
    try:
        from src.api.admin.corrections_router import (
            _bust_serving_cache as _bust,
        )
        _bust()
    except Exception:  # noqa: BLE001 -- never 500 the admin page over this
        logger.debug("could not bust the serving cache", exc_info=True)


def _pin_pattern(question: str) -> str:
    """A starting regex for "questions like this one".

    Deliberately literal: the whole question, escaped, case-insensitive. An
    operator who wants it broader can widen it in the box -- that is a
    deliberate edit they can see. Guessing at a loose pattern on their
    behalf would silently pin an answer to questions nobody checked.
    """
    import re as _re
    q = " ".join((question or "").split())[:200]
    return f"(?i){_re.escape(q)}" if q else ""


def _ticket_actions(tid: str, status: str, kq: str) -> str:
    """The transitions available FROM `status`, as labelled buttons."""
    base = f"/admin/tickets/{tid}/status?{kq}"
    if status == "open":
        return (ui.action(f"{base}&to=in_progress", "Start working",
                          primary=True)
                + ui.action(f"{base}&to=done", "Mark done"))
    if status == "in_progress":
        return (ui.action(f"{base}&to=done", "Mark done", primary=True)
                + ui.action(f"{base}&to=open", "Back to open", ghost=True))
    return ui.action(f"{base}&to=open", "Reopen", ghost=True)


def render_admin_list(tickets: list[dict], key: str,
                      counts: "Optional[dict]" = None,
                      show_done: bool = False) -> str:
    kq = f"key={ui.e(key)}" if key else ""
    kq_amp = f"?{kq}" if kq else ""
    cards = []
    for t in tickets:
        tid = str(t.get("id", ""))
        status = normalize_status(t.get("status"))
        mail_pill = (
            "" if t.get("emailSent")
            else " <span class='pill warn'>email failed</span>"
        )
        src = str(t.get("sourceUrl") or "").strip()
        # The handoff the old page was missing: from a ticket straight to
        # the tool that fixes it, with the ticket's URL prefilled.
        fix_href = "/admin/corrections/view" + (f"?{kq}" if kq else "")
        if src:
            sep = "&" if kq else "?"
            fix_href = f"/admin/corrections/view{kq_amp}{sep}target={ui.e(src)}"
        cards.append(
            f"<div class='card{' attn' if status == 'open' else ''}'>"
            f"<div class='meta'>{ui.pill(status, extra=mail_pill)}"
            f"<span>{ui.e(local_ts(t.get('createdAt')))}</span>"
            f"<span>{ui.e(t.get('librarianName'))} "
            f"&lt;{ui.e(t.get('librarianEmail'))}&gt;</span></div>"
            f"<div class='q'>{ui.e(t.get('question'))}</div>"
            f"<dl>"
            f"<dt>Bot said</dt><dd>{ui.e(t.get('botAnswer'))}</dd>"
            f"<dt>Should say</dt><dd>{ui.e(t.get('expectedAnswer'))}</dd>"
            + (f"<dt>Source</dt><dd><a href='{ui.e(src)}'>{ui.e(src)}</a></dd>"
               if src else "")
            + f"</dl>"
            f"<div class='acts'>"
            # The ticket's own page first: everything the follow-up needs is
            # there, so the operator stops leaving and coming back.
            f"{ui.action(f'/admin/tickets/{tid}{kq_amp}', 'Open ticket', primary=True)}"
            f"{_ticket_actions(tid, status, kq)}"
            f"{ui.action(fix_href, 'Fix content →')}</div>"
            f"</div>"
        )
    toggle = ui.action(
        f"/admin/tickets/view?{kq}" + ("" if show_done else "&show=all"),
        "Hide finished" if show_done else "Show finished too", ghost=True)
    body = (
        f"<h1>Correction tickets</h1>"
        f"<p class='lede'>Reports from library staff. Work them "
        f"open &rarr; in progress &rarr; done; each ticket links straight "
        f"to the corrections tool.</p>"
        f"<div class='acts' style='margin-bottom:1rem'>{toggle}</div>"
        + ("".join(cards) or ui.empty(
            "No tickets waiting. Staff submit them from the librarian hub."))
    )
    return ui.page("Correction tickets", body,
                   current="/admin/tickets/view", key=key, counts=counts)


# --- Router builder --------------------------------------------------------


def build_ticket_router(deps: dict):
    """Mount the ticket surfaces. deps: db, guard (admin), librarian_code."""
    from fastapi import APIRouter, Depends, HTTPException  # type: ignore
    from fastapi.responses import HTMLResponse  # type: ignore

    db = deps["db"]
    admin_guard = deps["guard"]
    librarian_code: str = (deps.get("librarian_code") or "").strip()

    router = APIRouter(tags=["tickets"])

    async def librarian_guard(request: Request) -> str:
        """Fail-closed shared-code gate for the librarian surface."""
        supplied = request.query_params.get("key", "")
        if not supplied and request.method == "POST":
            form = await request.form()
            supplied = str(form.get("key") or "")
        if not librarian_code or supplied != librarian_code:
            raise HTTPException(
                status_code=401,
                detail="Missing or wrong access code. Ask the library web "
                       "services team for the ticket-form link.",
            )
        return supplied

    @router.get("/librarian/ticket", response_class=HTMLResponse)
    async def ticket_form(request: Request):
        key = await librarian_guard(request)
        return HTMLResponse(render_form(key))

    @router.post("/librarian/ticket", response_class=HTMLResponse)
    async def ticket_submit(request: Request):
        key = await librarian_guard(request)
        form = dict(await request.form())
        clean, errors = validate_ticket(form)
        if errors:
            return HTMLResponse(render_form(key, clean, errors), status_code=422)

        row = await db.correctionticket.create(data={
            "librarianName": clean["librarian_name"],
            "librarianEmail": clean["librarian_email"],
            "question": clean["question"],
            "botAnswer": clean["bot_answer"],
            "expectedAnswer": clean["expected_answer"],
            "sourceUrl": clean["source_url"],
        })

        # Email AFTER the row is durable; a mail failure must not lose
        # the ticket (send_alert_email never raises).
        from src.observability.alerting import send_alert_email
        sent = send_alert_email(
            subject=f"\U0001f4cb Chatbot correction ticket from "
                    f"{clean['librarian_name']}",
            body=ticket_email_body({**clean, "id": row.id}),
        )
        if sent:
            await db.correctionticket.update(
                where={"id": row.id}, data={"emailSent": True},
            )
        return HTMLResponse(render_thanks(row.id, sent, key))

    @router.get("/admin/tickets/view", response_class=HTMLResponse,
                dependencies=[Depends(admin_guard)])
    async def tickets_list(request: Request):
        key = request.query_params.get("key", "")
        show_done = request.query_params.get("show", "") == "all"
        where = {} if show_done else {"status": {"not": "done"}}
        rows = await db.correctionticket.find_many(
            where=where, order={"createdAt": "desc"}, take=200,
        )
        from src.api.admin.review_queries import dashboard_counts
        counts = await dashboard_counts(db)
        return HTMLResponse(render_admin_list(
            [r.model_dump() if hasattr(r, "model_dump") else vars(r)
             for r in rows],
            key, counts=counts, show_done=show_done,
        ))

    @router.get("/admin/tickets/{ticket_id}", response_class=HTMLResponse,
                dependencies=[Depends(admin_guard)])
    async def ticket_detail(ticket_id: str, key: str = "",
                            msg: str = "") -> Any:
        """One ticket, plus everything the follow-up needs.

        The list view could only hand you the ticket and a link to the
        corrections tool. Deciding whether a report was real meant leaving
        for the conversation log, coming back, leaving again for the
        corrections form and re-typing what you had just read. This page
        carries the transcript, how often the same thing was asked, and a
        correction form already filled in from the ticket.
        """
        kq = f"key={ui.e(key)}" if key else ""
        kq_amp = f"?{kq}" if kq else ""
        back = f"/admin/tickets/view{kq_amp}"
        try:
            t = await db.correctionticket.find_unique(where={"id": ticket_id})
        except Exception:  # noqa: BLE001
            t = None
        if t is None:
            return HTMLResponse(ui.page("Ticket", (
                f"<h1>Ticket not found</h1>"
                f"<p class='dim'>No ticket with id <code>{ui.e(ticket_id)}</code>.</p>"
                f"{ui.action(back, '← back to the queue', ghost=True)}"),
                current="/admin/tickets/view", key=key), status_code=404)

        question = getattr(t, "question", "") or ""
        status = normalize_status(getattr(t, "status", "open"))
        src = str(getattr(t, "sourceUrl", "") or "").strip()

        # --- what else this question did ---
        asks = await find_asks_like(db, question)
        if asks:
            rows = "".join(
                f"<tr><td class='dim' style='white-space:nowrap'>{ui.e(a['when'])}</td>"
                f"<td><a href='/admin/review/{ui.e(a['conversation_id'])}{kq_amp}'>"
                f"{ui.e(a['content'][:110])}</a></td>"
                f"<td class='dim'>{int(a['overlap'] * 100)}%</td></tr>"
                for a in asks
            )
            asks_html = (
                f"<h2>Asked {len(asks)} time(s) like this</h2>"
                f"<p class='dim'>Loose text match, newest first — a lead for "
                f"how often this bites, not a measurement. The percentage is "
                f"how much of the ticket's wording each one shares.</p>"
                f"<table><tr><th>When</th><th>What they typed</th>"
                f"<th>Match</th></tr>{rows}</table>"
            )
        else:
            asks_html = (
                "<h2>Asked how often?</h2><p class='dim'>No other conversation "
                "matches this wording. Either it happened once, or the "
                "librarian paraphrased what the patron typed.</p>"
            )

        # --- the transcript, if the exact question is in one ---
        convo_html = ""
        exact = next((a for a in asks if a["overlap"] >= 0.99), None)
        if exact and exact["conversation_id"]:
            d = await conversation_detail(db, exact["conversation_id"])
            if d:
                turns = "".join(
                    f"<div class='turn {ui.e(m.get('type', ''))}'>"
                    f"<b>{'Patron' if m.get('type') == 'user' else 'Chatbot'}</b>"
                    f"<div>{ui.e((m.get('content') or '')[:900])}</div></div>"
                    for m in (d.get("messages") or [])
                )
                convo_html = (
                    f"<h2>The conversation it came from</h2>"
                    f"<div class='transcript'>{turns}</div>"
                    f"{ui.action(f'/admin/review/' + ui.e(exact['conversation_id']) + kq_amp, 'Full detail →', ghost=True)}"
                )

        # --- correction form, prefilled ---
        note = (f"<div class='ok' role='status' style='margin:.75rem 0'>{ui.e(msg)}</div>"
                if msg else "")
        pattern = _pin_pattern(question)
        form = (
            f"<h2>Write the correction</h2>"
            f"<p class='dim'>Pins an answer to questions matching the pattern. "
            f"Takes effect on the next turn — no deploy. Expires in 180 days "
            f"so nobody inherits a rule nobody remembers.</p>"
            f"<form method='post' action='/admin/tickets/{ui.e(ticket_id)}/correct{kq_amp}'>"
            f"<label for='c-pat'>Fires on questions matching</label>"
            f"<input id='c-pat' name='query_pattern' value='{ui.e(pattern)}' "
            f"style='width:100%;font-family:ui-monospace,monospace'>"
            f"<label for='c-rep'>Answer to give</label>"
            f"<textarea id='c-rep' name='replacement' rows='5' "
            f"style='width:100%'>{ui.e(getattr(t, 'expectedAnswer', '') or '')}</textarea>"
            f"<label for='c-by'>Your email (recorded on the rule)</label>"
            f"<input id='c-by' name='created_by' type='email' required "
            f"placeholder='you@miamioh.edu' style='max-width:24rem'>"
            f"<div class='acts' style='margin-top:.8rem'>"
            f"<button type='submit'>Create the correction</button></div>"
            f"</form>"
        )

        body = (
            f"{ui.action(back, '← back to the queue', ghost=True)}"
            f"<h1>Correction ticket</h1>{note}"
            f"<div class='card'>"
            f"<div class='meta'>{ui.pill(status)}"
            f"<span>{ui.e(local_ts(getattr(t, 'createdAt', None)))}</span>"
            f"<span>{ui.e(getattr(t, 'librarianName', ''))} "
            f"&lt;{ui.e(getattr(t, 'librarianEmail', ''))}&gt;</span></div>"
            f"<div class='q'>{ui.e(question)}</div>"
            f"<dl><dt>Bot said</dt><dd>{ui.e(getattr(t, 'botAnswer', ''))}</dd>"
            f"<dt>Should say</dt><dd>{ui.e(getattr(t, 'expectedAnswer', ''))}</dd>"
            + (f"<dt>Source</dt><dd><a href='{ui.e(src)}'>{ui.e(src)}</a></dd>"
               if src else "")
            + f"</dl>"
            f"<div class='acts'>{_ticket_actions(ticket_id, status, kq)}</div>"
            f"</div>"
            f"<style>.transcript{{border:1px solid #e3e3e3;border-radius:8px;"
            f"padding:.4rem .8rem;margin:.6rem 0}}"
            f".turn{{padding:.5rem 0;border-bottom:1px solid #f0f0f0}}"
            f".turn:last-child{{border-bottom:0}}"
            f".turn.user b{{color:#8E1224}}.turn b{{display:block;"
            f"font-size:.72rem;letter-spacing:.05em;text-transform:uppercase}}"
            f"label{{display:block;margin:.7rem 0 .2rem;font-weight:600;"
            f"font-size:.85rem}}</style>"
            f"{convo_html}{asks_html}{form}"
        )
        return HTMLResponse(ui.page("Ticket", body,
                                    current="/admin/tickets/view", key=key))

    @router.post("/admin/tickets/{ticket_id}/correct",
                 response_class=HTMLResponse,
                 dependencies=[Depends(admin_guard)])
    async def ticket_correct(ticket_id: str, request: Request,
                             key: str = "") -> Any:
        """Create the correction from the ticket page, then come back to it.

        Posting here rather than to /admin/corrections keeps the operator on
        the ticket: the point of the page is that finishing a report does not
        require going somewhere else and retyping it.
        """
        form = await request.form()
        kq_amp = f"?key={ui.e(key)}" if key else ""
        back = f"/admin/tickets/{ui.e(ticket_id)}{kq_amp}"

        created_by = str(form.get("created_by") or "").strip()
        replacement = str(form.get("replacement") or "").strip()
        pattern = str(form.get("query_pattern") or "").strip()
        problem = (
            "Enter your email — a correction with no author cannot be reviewed."
            if not created_by else
            "Enter the answer the bot should give." if not replacement else
            "The pattern is empty, so this rule would fire on nothing."
            if not pattern else ""
        )
        if not problem:
            try:
                import re as _re
                _re.compile(pattern)
            except _re.error as e:
                problem = f"That pattern is not a valid regular expression: {e}"
        if problem:
            sep = "&" if key else "?"
            return RedirectResponse(f"{back}{sep}msg={_q(problem)}",
                                    status_code=303)

        try:
            await db.manualcorrection.create(data={
                "scope": "global", "target": "*", "action": "pin",
                "replacement": replacement, "queryPattern": pattern,
                "reason": f"correction ticket {ticket_id}",
                "createdBy": created_by,
                "expiresAt": _default_expiry(),
            })
        except Exception as e:  # noqa: BLE001
            logger.error("could not create correction from ticket %s: %s",
                         ticket_id, e)
            sep = "&" if key else "?"
            return RedirectResponse(
                f"{back}{sep}msg={_q('Could not save the correction — the log has why.')}",
                status_code=303)

        _bust_serving_cache()
        logger.info("correction created from ticket %s by %s", ticket_id,
                    created_by)
        sep = "&" if key else "?"
        return RedirectResponse(
            f"{back}{sep}msg={_q('Correction saved. It applies on the next turn.')}",
            status_code=303)

    @router.get("/admin/tickets/{ticket_id}/status",
                response_class=HTMLResponse,
                dependencies=[Depends(admin_guard)])
    async def ticket_set_status(ticket_id: str, request: Request):
        """Set an EXPLICIT target state (?to=open|in_progress|done).

        Replaces the old cycling /mark endpoint, which advanced to
        whatever came next and wrapped done back to open -- so a
        finished ticket could silently reopen (operator report
        2026-07-28). An unknown/absent target is rejected rather than
        guessed at.
        """
        target = normalize_status(request.query_params.get("to"))
        if request.query_params.get("to") not in VALID_STATUSES:
            raise HTTPException(status_code=400,
                                detail=f"to= must be one of {VALID_STATUSES}")
        row = await db.correctionticket.find_unique(where={"id": ticket_id})
        if row is None:
            raise HTTPException(status_code=404, detail="no such ticket")
        from datetime import datetime, timezone
        data: dict = {"status": target}
        # reviewedAt records when it LEFT the open pile; reopening clears
        # it so the timestamp never contradicts the status.
        data["reviewedAt"] = (
            None if target == "open" else datetime.now(timezone.utc)
        )
        await db.correctionticket.update(where={"id": ticket_id}, data=data)
        back = "/admin/tickets/view" + (
            f"?key={request.query_params.get('key', '')}" if key_present(request)
            else "")
        return HTMLResponse(
            f"<!doctype html><meta charset='utf-8'>"
            f"<meta http-equiv='refresh' content='0;url={ui.e(back)}'>ok"
        )

    return router
