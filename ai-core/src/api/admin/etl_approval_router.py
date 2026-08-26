"""Web approval for an ETL diff -- read it, sign it, submit it.

WHY THIS EXISTS
    The librarian gate has always been a file on disk: `prepare` writes
    `data/diffs/<stamp>.approval`, somebody opens it in an editor, fills in
    three fields and saves. That works for whoever has a shell on the box,
    which is one person. The colleagues who actually know whether a page
    should be in the corpus do not have one, so in practice the reviewer and
    the operator were the same person -- which is not a gate.

WHAT THIS DOES NOT CHANGE
    `gate.verify_gate` remains the only authority on whether an apply may
    proceed, and this router writes a token in exactly the format it parses.
    After writing, it re-runs verify_gate and reports what that says rather
    than what it hoped -- so a token this page produces can never be one the
    CLI would reject.

    The anti-tamper binding is kept end to end: the hash of the diff being
    displayed is carried in the form and re-checked on submit. If a new
    `prepare` ran while somebody had the page open, their signature is
    refused rather than applied to a diff they never read.

WHY IT DOES NOT RUN THE APPLY
    Approving is a judgement; applying is a 1.4 GB job that measurably costs
    3.6x on answer latency and has OOM-killed this box before. Doing it
    inside a request handler would tie up a worker for minutes and could
    take the bot down while patrons are asking. The documented rule is that
    an apply runs in a quiet window, deliberately. So this records the
    approval and says so; the apply stays a separate, chosen act.

AUTHORISATION
    Its own allowlist and passphrase, deliberately NOT the kill switch's.
    Approving a corpus change and taking the service offline are different
    authorities, and holding one should not confer the other.

        ETL_APPROVERS=a@miamioh.edu,b@miamioh.edu
        ETL_APPROVAL_PASSWORD=<shared passphrase>

    Both fail closed: unset means nobody can approve here, and the file on
    disk remains the way in for whoever has a shell.
"""

from __future__ import annotations

import datetime as dt
import hmac
import logging
import os
import re
from pathlib import Path
from typing import Optional

from scripts.etl import gate
from src.api.admin import admin_ui as ui
from src.api.admin.killswitch_router import (
    attempt_key,
    note_failed_attempt,
    reset_attempts,
)

# `Request` MUST be a module global.
#
# With `from __future__ import annotations` every annotation is a string,
# and FastAPI resolves those against module globals. A Request imported
# inside the factory is invisible there, so FastAPI reads `request: Request`
# as a request BODY and every POST returns 422 before the handler runs.
# This exact bug has cost this codebase four separate outages; the guard is
# cheap and the failure is silent, so it is written out rather than assumed.
try:  # pragma: no cover - import shape, not behaviour
    from fastapi import Request
except Exception:  # pragma: no cover
    Request = object  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

_NOINDEX = {"X-Robots-Tag": "noindex, nofollow"}

_THROTTLED = ("Too many failed attempts from this address. Wait a few "
              "minutes and try again.")

DIFF_DIR = Path(os.getenv("ETL_DIFF_DIR", "/opt/chatbot/ai-core/data/diffs"))


def approvers() -> list:
    """Emails permitted to sign a diff, lowercased.

    Read per call rather than at import so a .env correction takes effect on
    the next restart without a code change, and so tests can set it.
    """
    raw = os.getenv("ETL_APPROVERS", "")
    return [x.strip().lower() for x in raw.split(",") if x.strip()]


def check_approver(email: str, password: str) -> Optional[str]:
    """None if this person may sign, else the reason they may not."""
    allowed = approvers()
    secret = os.getenv("ETL_APPROVAL_PASSWORD", "")
    if not allowed:
        return ("ETL_APPROVERS is not set, so nobody can approve here. The "
                ".approval file on disk is still the way in.")
    if not secret:
        return ("ETL_APPROVAL_PASSWORD is not set, so nobody can approve "
                "here. The .approval file on disk is still the way in.")
    who = (email or "").strip().lower()
    if not who:
        return "Enter your Miami email."
    if who not in allowed:
        return "That email is not on the approver list for the corpus."
    # compare_digest, not ==, so a wrong passphrase takes the same time to
    # reject whatever prefix it shares with the real one.
    if not hmac.compare_digest((password or "").strip(), secret):
        return "Wrong passphrase."
    return None


def latest_diff() -> Optional[Path]:
    """The newest prepared diff, or None if there is not one."""
    try:
        diffs = sorted(DIFF_DIR.glob("*.md"))
    except OSError:
        return None
    return diffs[-1] if diffs else None


def _applied_marker(diff_path: Path) -> Optional[Path]:
    p = diff_path.with_suffix(".applied")
    return p if p.exists() else None


def sign(diff_path: Path, *, email: str, when: Optional[dt.datetime] = None) -> None:
    """Fill in the three fields the token template leaves blank.

    Rewrites the file rather than appending, so signing twice cannot leave
    two `approved_by_email` lines for the parser to choose between.
    """
    token_path = diff_path.with_suffix(gate.APPROVAL_FILENAME_SUFFIX)
    stamp = (when or dt.datetime.now(dt.timezone.utc)).isoformat(
        timespec="seconds")
    out = []
    for line in token_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("approved_by_email:"):
            out.append(f"approved_by_email: {email}")
        elif line.startswith("approved_at:"):
            out.append(f"approved_at: {stamp}")
        else:
            out.append(line)
    token_path.write_text("\n".join(out) + "\n", encoding="utf-8")


REJECTED_SUFFIX = ".rejected"


def rejection_of(diff_path: Path) -> Optional[dict]:
    """The recorded objection to this diff, or None."""
    p = diff_path.with_suffix(REJECTED_SUFFIX)
    if not p.exists():
        return None
    out: dict = {"by": "", "at": "", "reason": "", "urls": []}
    section = None
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.startswith("rejected_by:"):
                out["by"] = line.split(":", 1)[1].strip()
            elif line.startswith("rejected_at:"):
                out["at"] = line.split(":", 1)[1].strip()
            elif line.startswith("reason:"):
                section = "reason"
                out["reason"] = line.split(":", 1)[1].strip()
            elif line.startswith("urls:"):
                section = "urls"
            elif line.startswith("- ") and section == "urls":
                out["urls"].append(line[2:].strip())
            elif section == "reason" and line.strip():
                out["reason"] += " " + line.strip()
    except OSError:
        return None
    return out


def record_rejection(diff_path: Path, *, email: str, reason: str,
                     urls: "list", when: Optional[dt.datetime] = None) -> Path:
    """Write the objection beside the diff.

    A REJECTION IS A RECORD, NOT AN EDIT.

    The obvious next step -- let the reviewer untick pages and have the run
    skip them -- would mean a web form rewriting the crawl's exclusion rules,
    which live in config.py and are code. A form that silently changes what
    the corpus contains is worse than one that cannot: the change would
    outlive the conversation that motivated it, with nobody's name on it.

    So the objection is written down with the reviewer's name, the urls they
    named, and their reason, and the operator makes the config change
    deliberately. Same shape as the approval it sits beside.
    """
    stamp = (when or dt.datetime.now(dt.timezone.utc)).isoformat(
        timespec="seconds")
    lines = [
        "# ETL diff rejection",
        "#",
        "# A reviewer read this diff and objected. Nothing was applied.",
        "# The operator changes the crawl config and re-runs prepare; this",
        "# file is the record of why.",
        "",
        f"diff_file: {diff_path.name}",
        f"rejected_by: {email}",
        f"rejected_at: {stamp}",
        f"reason: {' '.join((reason or '').split())}",
        "urls:",
    ]
    lines += [f"- {u}" for u in urls] or ["# (none named)"]
    out = diff_path.with_suffix(REJECTED_SUFFIX)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def _mail_rejection(diff_path: Path, *, email: str, reason: str,
                    urls: "list") -> None:
    """Tell the operator. Best effort -- the file on disk is the record."""
    try:
        from src.observability.alerting import send_alert_email

        named = "\n".join(f"  {u}" for u in urls) or "  (none named)"
        send_alert_email(
            f"[chatbot] corpus diff sent back: {diff_path.name}",
            f"{email} read {diff_path.name} and did not approve it.\n\n"
            f"Their reason:\n  {' '.join((reason or '').split())}\n\n"
            f"Pages they named:\n{named}\n\n"
            f"Nothing has been applied. Change the crawl config, re-run "
            f"`--phase prepare`, and the review page will show the new diff.",
        )
    except Exception as e:  # noqa: BLE001 -- mail must not lose the record
        logger.warning("could not mail the rejection: %s", e)


# --- rendering the diff -------------------------------------------------
#
# The diff is markdown WE generate, so its vocabulary is known and small:
# headings, tables, list items, blockquotes, `code`, **bold** and the odd
# italic line. A dependency for that would be more surface than the job
# needs, and a general parser would still have to be told these rules.
#
# ESCAPING HAPPENS FIRST, before any markdown is interpreted. The diff
# carries urls and page titles harvested from the web; treated as trusted
# markup, a page title containing a tag would become live HTML on a page
# behind an approver's login. Escaped text is then linked and emphasised,
# which is safe because escaping cannot be undone by the steps after it.

_MD_BOLD = re.compile(r"\*\*(.+?)\*\*")
_MD_CODE = re.compile(r"`([^`]+)`")
_MD_LINK = re.compile(r"(https?://[^\s<>\"\')]+)")


def _inline(text: str) -> str:
    """Escaped text -> escaped text plus the inline markup we emit."""
    out = ui.e(text)
    out = _MD_CODE.sub(r"<code>\1</code>", out)
    out = _MD_BOLD.sub(r"<strong>\1</strong>", out)
    # The href keeps the escaped spelling on purpose: `&amp;` IS the correct
    # HTML for an ampersand in an attribute, and c.php guide urls have one.
    out = _MD_LINK.sub(
        r'<a href="\1" target="_blank" rel="noopener noreferrer">\1</a>', out)
    return out


def _is_table_rule(line: str) -> bool:
    return bool(line) and set(line) <= set("|-: ")


def render_markdown(md: str) -> str:
    """The diff as HTML. Handles only what write_diff_report emits."""
    html: list = []
    rows: list = []          # the table being accumulated
    para: list = []          # the paragraph being accumulated
    items: list = []         # the list being accumulated

    def flush_para():
        if para:
            html.append("<p>" + _inline(" ".join(para)) + "</p>")
            para.clear()

    def flush_list():
        if items:
            html.append("<ul>" + "".join(f"<li>{_inline(i)}</li>"
                                         for i in items) + "</ul>")
            items.clear()

    def flush_table():
        if not rows:
            return
        head, body = rows[0], rows[1:]
        cells = "".join(f"<th>{_inline(c)}</th>" for c in head)
        trs = "".join(
            "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>"
            for r in body)
        html.append(f"<div class='scroll'><table><thead><tr>{cells}</tr>"
                    f"</thead><tbody>{trs}</tbody></table></div>")
        rows.clear()

    def flush_all():
        flush_para()
        flush_list()
        flush_table()

    for raw in (md or "").splitlines():
        line = raw.rstrip()
        stripped = line.strip()

        if stripped.startswith("|"):
            flush_para()
            flush_list()
            if _is_table_rule(stripped):
                continue          # the |---|---| separator carries no data
            rows.append([c.strip() for c in stripped.strip("|").split("|")])
            continue
        flush_table()

        if not stripped:
            flush_para()
            flush_list()
            continue

        if stripped.startswith("- "):
            flush_para()
            items.append(stripped[2:])
            continue
        flush_list()

        if stripped.startswith("#"):
            flush_para()
            level = len(stripped) - len(stripped.lstrip("#"))
            # h1 in the diff is the report title; the page already has an h1,
            # so everything shifts down one to keep one h1 per document.
            tag = f"h{min(level + 1, 6)}"
            html.append(f"<{tag}>{_inline(stripped.lstrip('#').strip())}</{tag}>")
            continue

        if stripped.startswith(">"):
            flush_para()
            html.append("<blockquote>"
                        + _inline(stripped.lstrip('>').strip())
                        + "</blockquote>")
            continue

        if (len(stripped) > 2 and stripped.startswith("_")
                and stripped.endswith("_")):
            flush_para()
            html.append("<p><em>" + _inline(stripped[1:-1]) + "</em></p>")
            continue

        para.append(stripped)

    flush_all()
    return "".join(html)


def _summary_of(diff_path: Path) -> str:
    """The Summary block, which is what a reviewer reads first."""
    try:
        text = diff_path.read_text(encoding="utf-8")
    except OSError:
        return ""
    if "## Summary" not in text:
        return ""
    return text.split("## Summary", 1)[1].split("\n## ", 1)[0].strip()


def _section(diff_path: Path, heading: str) -> str:
    try:
        text = diff_path.read_text(encoding="utf-8")
    except OSError:
        return ""
    if heading not in text:
        return ""
    return text.split(heading, 1)[1].split("\n### ", 1)[0].split("\n## ", 1)[0]


def _md_table_rows(block: str) -> str:
    """The markdown table in `block`, as HTML rows. Crude on purpose --
    the diff is generated by us, so this is formatting, not parsing."""
    rows = []
    for line in block.splitlines():
        line = line.strip()
        if not line.startswith("|") or set(line) <= set("|-: "):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        rows.append("<tr>" + "".join(f"<td>{ui.e(c)}</td>" for c in cells)
                    + "</tr>")
    return "".join(rows)


def render_page(key: str, message: str = "", ok: str = "") -> str:
    diff = latest_diff()
    if diff is None:
        return ui.page("Corpus review",
                       "<p>No prepared diff is waiting. Run "
                       "<code>--phase prepare</code> first.</p>",
                       current="/admin/etl", key=key)

    decision = gate.verify_gate(diff)
    token = decision.token
    applied = _applied_marker(diff)
    digest = gate.hash_diff_file(diff)

    banner = ""
    if message:
        banner += f"<p class='warn'>{ui.e(message)}</p>"
    if ok:
        banner += f"<p class='good'>{ui.e(ok)}</p>"

    rejected = rejection_of(diff)
    if applied:
        state = ("<p class='good'>This diff has already been applied "
                 f"({ui.e(applied.name)}).</p>")
    elif decision.proceed:
        who = (token.approved_by_email if token else "") or "someone"
        state = (f"<p class='good'>Signed by {ui.e(who)}. An operator can "
                 "now run the apply in a quiet window.</p>")
    else:
        state = f"<p class='warn'>Not yet approved — {ui.e(decision.reason)}</p>"

    objection = ""
    if rejected:
        named = "".join(f"<li><code>{ui.e(u)}</code></li>"
                        for u in rejected.get("urls") or [])
        objection = (
            "<div class='warnbox'>"
            f"<h2>Sent back by {ui.e(rejected.get('by') or 'a reviewer')}</h2>"
            f"<p>{ui.e(rejected.get('reason') or '(no reason given)')}</p>"
            + (f"<p>Pages they named:</p><ul>{named}</ul>" if named else "")
            + "<p class='hint'>Recorded, not applied. An operator changes the "
              "crawl config and re-runs <code>--phase prepare</code>. Approving "
              "below is still possible if the objection has been settled.</p>"
            "</div>")

    lost = _md_table_rows(_section(diff, "### Lost outright"))
    lost_html = (f"<table><thead><tr><th>chunks</th><th>URL</th></tr></thead>"
                 f"<tbody>{lost}</tbody></table>" if lost else
                 "<p>Nothing would be lost outright.</p>")

    body = diff.read_text(encoding="utf-8")

    form = ""
    if not decision.proceed and not applied:
        form = (
            "<h2>Sign this review</h2>"
            "<form method='post' action='/admin/etl/approve"
            f"?key={ui.e(key)}'>"
            f"<input type='hidden' name='diff_hash' value='{ui.e(digest)}'>"
            f"<input type='hidden' name='diff_file' value='{ui.e(diff.name)}'>"
            "<label for='email'>Your Miami email</label>"
            "<input type='email' id='email' name='email' required "
            "autocomplete='username'>"
            "<label for='password'>Approval passphrase</label>"
            "<input type='password' id='password' name='password' required "
            "autocomplete='current-password'>"
            "<label class='ack'><input type='checkbox' name='ack' value='yes' "
            "required> I have read the diff above and approve promoting it "
            "to the live index.</label>"
            "<button type='submit'>Approve this diff</button>"
            "</form>"
            "<h2>Or send it back</h2>"
            "<p class='hint'>If something here should not be indexed, or a "
            "page you still need is being dropped, say so. Nothing is "
            "applied and the operator gets your note.</p>"
            "<form method='post' action='/admin/etl/reject"
            f"?key={ui.e(key)}'>"
            f"<input type='hidden' name='diff_hash' value='{ui.e(digest)}'>"
            f"<input type='hidden' name='diff_file' value='{ui.e(diff.name)}'>"
            "<label for='r_email'>Your Miami email</label>"
            "<input type='email' id='r_email' name='email' required "
            "autocomplete='username'>"
            "<label for='r_password'>Approval passphrase</label>"
            "<input type='password' id='r_password' name='password' required "
            "autocomplete='current-password'>"
            "<label for='reason'>What is wrong with it</label>"
            "<textarea id='reason' name='reason' rows='3' required "
            "placeholder='e.g. the events guide should not be in the corpus "
            "-- it goes stale every semester'></textarea>"
            "<label for='urls'>Pages you object to, one per line "
            "(optional)</label>"
            "<textarea id='urls' name='urls' rows='4' "
            "placeholder='https://www.lib.miamioh.edu/...'></textarea>"
            "<button type='submit' class='ghost'>Send back without "
            "approving</button>"
            "</form>"
        )

    return ui.page(
        "Corpus review",
        banner
        + f"<h1>{ui.e(diff.name)}</h1>"
        + state
        + objection
        + "<h2>Summary</h2>"
        + f"<div class='md'>{render_markdown(_summary_of(diff))}</div>"
        + "<h2>Would be lost outright</h2>"
        + "<p class='hint'>The column to read. A page you still need "
          "appearing here is the thing to catch.</p>"
        + lost_html
        + form
        + "<h2>Full diff</h2>"
        + f"<div class='md'>{render_markdown(body)}</div>",
        current="/admin/etl", key=key,
    )


def build_etl_approval_router(deps: dict):
    from fastapi import APIRouter, Depends, Form  # type: ignore
    from fastapi.responses import HTMLResponse, RedirectResponse  # type: ignore

    async def _no_guard() -> None:
        """This page protects itself with email + passphrase, like the
        kill switch. A guard may still be injected by a deployment that
        wants one in front."""
        return None

    guard = deps.get("guard") or _no_guard
    router = APIRouter(prefix="/admin", tags=["admin"])

    @router.get("/etl", response_class=HTMLResponse)
    async def etl_page(key: str = "", _u=Depends(guard)):
        return HTMLResponse(render_page(key), headers=_NOINDEX)

    @router.post("/etl/approve", response_class=HTMLResponse)
    async def approve(request: Request, key: str = "", email: str = Form(""),
                      password: str = Form(""), ack: str = Form(""),
                      diff_hash: str = Form(""), diff_file: str = Form(""),
                      _u=Depends(guard)):
        diff = latest_diff()
        if diff is None:
            return HTMLResponse(
                render_page(key, "No prepared diff is waiting."),
                status_code=404, headers=_NOINDEX)

        # THE DIFF THEY READ IS THE DIFF THEY SIGN.
        #
        # If a prepare ran while this page was open, the file under the same
        # name is different content. Signing it would attach a real person's
        # name to a change they never saw, which is the one thing the gate
        # exists to prevent.
        if diff.name != diff_file or gate.hash_diff_file(diff) != diff_hash:
            return HTMLResponse(
                render_page(key, "The diff changed while you were reading it. "
                                 "Nothing was signed -- review the new one."),
                status_code=409, headers=_NOINDEX)

        if not (ack or "").strip():
            return HTMLResponse(
                render_page(key, "Tick the box to confirm you read the diff."),
                status_code=400, headers=_NOINDEX)

        why = check_approver(email, password)
        if why:
            # Never echo the passphrase, not even to say it was wrong.
            logger.warning("corpus approval REFUSED for %r: %s",
                           (email or "").strip().lower(), why)
            if not note_failed_attempt(attempt_key(request)):
                logger.warning("corpus approval attempts THROTTLED for %s",
                               attempt_key(request))
                return HTMLResponse(render_page(key, _THROTTLED),
                                    status_code=429, headers=_NOINDEX)
            return HTMLResponse(render_page(key, why), status_code=403,
                                headers=_NOINDEX)
        reset_attempts(attempt_key(request))

        who = (email or "").strip().lower()
        sign(diff, email=who)

        # Report what the gate says, not what we hoped. A token this page
        # writes must never be one the CLI would refuse.
        decision = gate.verify_gate(diff)
        if not decision.proceed:
            logger.error("corpus approval written but gate still refuses: %s",
                         decision.reason)
            return HTMLResponse(
                render_page(key, f"Signature written but the gate still "
                                 f"refuses it: {decision.reason}"),
                status_code=500, headers=_NOINDEX)

        logger.warning("corpus diff %s APPROVED by %s", diff.name, who)
        return RedirectResponse(f"/admin/etl?key={key}&ok=1", status_code=303)

    @router.post("/etl/reject", response_class=HTMLResponse)
    async def reject(request: Request, key: str = "", email: str = Form(""),
                     password: str = Form(""), reason: str = Form(""),
                     urls: str = Form(""), diff_hash: str = Form(""),
                     diff_file: str = Form(""), _u=Depends(guard)):
        diff = latest_diff()
        if diff is None:
            return HTMLResponse(
                render_page(key, "No prepared diff is waiting."),
                status_code=404, headers=_NOINDEX)

        # Same binding as approving: an objection to a diff that has since
        # been replaced is an objection to something nobody can act on.
        if diff.name != diff_file or gate.hash_diff_file(diff) != diff_hash:
            return HTMLResponse(
                render_page(key, "The diff changed while you were reading it. "
                                 "Nothing was recorded -- review the new one."),
                status_code=409, headers=_NOINDEX)

        if not (reason or "").strip():
            return HTMLResponse(
                render_page(key, "Say what is wrong with it, so the operator "
                                 "knows what to change."),
                status_code=400, headers=_NOINDEX)

        why = check_approver(email, password)
        if why:
            logger.warning("corpus rejection REFUSED for %r: %s",
                           (email or "").strip().lower(), why)
            if not note_failed_attempt(attempt_key(request)):
                return HTMLResponse(render_page(key, _THROTTLED),
                                    status_code=429, headers=_NOINDEX)
            return HTMLResponse(render_page(key, why), status_code=403,
                                headers=_NOINDEX)
        reset_attempts(attempt_key(request))

        who = (email or "").strip().lower()
        named = [u.strip() for u in (urls or "").splitlines() if u.strip()]
        record_rejection(diff, email=who, reason=reason, urls=named)
        _mail_rejection(diff, email=who, reason=reason, urls=named)
        logger.warning("corpus diff %s SENT BACK by %s (%d page(s) named)",
                       diff.name, who, len(named))
        return RedirectResponse(f"/admin/etl?key={key}", status_code=303)

    return router
