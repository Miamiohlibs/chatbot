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

    if applied:
        state = ("<p class='good'>This diff has already been applied "
                 f"({ui.e(applied.name)}).</p>")
    elif decision.proceed:
        who = (token.approved_by_email if token else "") or "someone"
        state = (f"<p class='good'>Signed by {ui.e(who)}. An operator can "
                 "now run the apply in a quiet window.</p>")
    else:
        state = f"<p class='warn'>Not yet approved — {ui.e(decision.reason)}</p>"

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
        )

    return ui.page(
        "Corpus review",
        banner
        + f"<h1>{ui.e(diff.name)}</h1>"
        + state
        + "<h2>Summary</h2>"
        + f"<pre class='summary'>{ui.e(_summary_of(diff))}</pre>"
        + "<h2>Would be lost outright</h2>"
        + "<p class='hint'>The column to read. A page you still need "
          "appearing here is the thing to catch.</p>"
        + lost_html
        + form
        + "<h2>Full diff</h2>"
        + f"<pre class='diff'>{ui.e(body)}</pre>",
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

    return router
