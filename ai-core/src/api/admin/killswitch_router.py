"""
One-click shutdown, as promised to colleagues: a single page with a button
that takes the bot out of service, and another that puts it back.

WHY A FLAG AND NOT `systemctl stop`
    Stopping the process would make the widget on the library website fail
    with a network error -- a patron sees a broken page and no explanation.
    This keeps the service up and answers every turn with a maintenance
    notice instead, so the page still works and says something honest.

    It also means recovery is one click by the operator rather than a shell
    on the server, which is the point of "one-click".

THE FLAG IS A FILE, ON PURPOSE
    `data/SERVICE_PAUSED` on disk, not a variable:
      * it SURVIVES a restart -- if the bot is paused because it is
        misbehaving, a crash-restart must not quietly put it back in service
      * it can be set or cleared without this router, by touching or deleting
        the file, so a stuck web surface never leaves the operator without a
        way out
      * every worker sees the same state, which a per-process variable would
        not guarantee

FAIL-CLOSED AUTH
    Mounted only when `ADMIN_API_TOKEN` is set, and every route is behind the
    same guard as the rest of /admin.

SECOND FACTOR ON THE SWITCH ITSELF
    Operator ruling 2026-08-10: the token alone is too easy. Taking the bot
    out of service -- or putting it BACK, which matters just as much when it
    is out because it is misbehaving -- also needs an operator email from
    `SERVICE_PAUSE_OPERATORS` and the shared passphrase in
    `SERVICE_PAUSE_PASSWORD`. Both live in .env and never in this repo.

    Be clear about what that buys, because it is easy to overrate: the email
    is TYPED, not proven. Anyone holding the admin token and the passphrase
    can enter any name on the list. What it gives is a deliberate-action
    speed bump, an accountability record of who says they did it, and a
    restriction to a known set of people. Real identity needs SSO, which is
    a separate piece of work.

    Unconfigured means NOBODY can switch the service from the web page. That
    is safe rather than reckless only because the flag is a file: an
    operator with a shell can still `touch data/SERVICE_PAUSED` during an
    incident (see above). Keep that escape hatch working.
"""

from __future__ import annotations

import datetime as dt
import hmac
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_FLAG_PATH = Path(
    os.getenv("SERVICE_PAUSE_FLAG",
              str(Path(__file__).resolve().parents[3] / "data" / "SERVICE_PAUSED"))
)

PAUSED_MESSAGE = (
    "The library chatbot is temporarily unavailable for maintenance. "
    "For help right now, please use Ask Us to reach a librarian: "
    "https://www.lib.miamioh.edu/research/research-support/ask/"
)


def is_paused() -> bool:
    """Cheap enough to call on every turn (a stat, no read)."""
    try:
        return _FLAG_PATH.exists()
    except Exception:  # noqa: BLE001 -- never let this decide by raising
        return False


def pause_reason() -> str:
    try:
        return _FLAG_PATH.read_text(encoding="utf-8").strip()
    except Exception:  # noqa: BLE001
        return ""


def pause(who: str = "operator", note: str = "") -> None:
    _FLAG_PATH.parent.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    _FLAG_PATH.write_text(
        f"paused_at: {stamp}\npaused_by: {who}\nnote: {note}\n",
        encoding="utf-8")
    logger.warning("SERVICE PAUSED by %s: %s", who, note or "(no note)")


def resume(who: str = "operator") -> None:
    try:
        _FLAG_PATH.unlink()
        logger.warning("SERVICE RESUMED by %s", who)
    except FileNotFoundError:
        pass


def allowed_operators() -> list[str]:
    """The emails permitted to switch the service, lowercased.

    Read per call rather than at import so a .env correction takes effect on
    the next restart without a code change, and so tests can set it.
    """
    raw = os.getenv("SERVICE_PAUSE_OPERATORS", "")
    return [e.strip().lower() for e in raw.split(",") if e.strip()]


def check_operator(email: str, password: str) -> Optional[str]:
    """None if this operator may switch the service, else why not.

    Fail-closed on missing configuration: an empty allowlist or an unset
    passphrase locks the web control for everyone rather than falling back
    to the token alone.
    """
    allowed = allowed_operators()
    secret = os.getenv("SERVICE_PAUSE_PASSWORD", "")
    if not allowed:
        return ("SERVICE_PAUSE_OPERATORS is not set, so nobody is authorised "
                "here. An operator with a shell can still touch the "
                "data/SERVICE_PAUSED flag file.")
    if not secret:
        return ("SERVICE_PAUSE_PASSWORD is not set, so nobody is authorised "
                "here. An operator with a shell can still touch the "
                "data/SERVICE_PAUSED flag file.")

    who = (email or "").strip().lower()
    if not who:
        return "Enter your Miami email."
    if who not in allowed:
        return "That email is not on the operator list for this control."
    # compare_digest, not ==, so a wrong passphrase takes the same time to
    # reject whatever prefix it shares with the real one.
    if not hmac.compare_digest((password or "").strip(), secret):
        return "Wrong passphrase."
    return None


def build_killswitch_router(deps: dict):
    """`deps` needs `guard` -- the same token dependency as /admin/review."""
    from fastapi import APIRouter, Depends, Form  # type: ignore
    from fastapi.responses import HTMLResponse, RedirectResponse  # type: ignore

    guard = deps["guard"]
    router = APIRouter(prefix="/admin", tags=["admin"])

    def _credentials(key: str, action: str, extra: str = "") -> str:
        """The email + passphrase pair both actions require."""
        from src.api.admin.admin_ui import e

        return f"""
              {extra}
              <label for="op-email-{action}">Your Miami email</label>
              <input id="op-email-{action}" name="email" type="email" required
                     autocomplete="username"
                     placeholder="you@miamioh.edu" style="max-width:24rem">
              <label for="op-pass-{action}">Passphrase</label>
              <input id="op-pass-{action}" name="password" type="password"
                     required autocomplete="current-password"
                     style="max-width:24rem">
              <small class="dim">Both are required. Your email is recorded in
              the log with this action.</small>"""

    def _page(key: str, error: str = "") -> str:
        from src.api.admin.admin_ui import e, page

        paused = is_paused()
        err = (f"<div class='err' role='alert' style='margin:.75rem 0'>"
               f"{e(error)}</div>") if error else ""
        if paused:
            body = f"""
            <div style="border:2px solid #b61e2e;padding:1.25rem;border-radius:8px">
              <h2 style="margin-top:0;color:#b61e2e">The bot is OUT OF SERVICE</h2>
              <p>Every question is being answered with a maintenance notice
                 pointing patrons at Ask Us. The widget still loads — nobody
                 sees a broken page.</p>
              <pre style="background:#f6f6f6;padding:.75rem">{e(pause_reason())}</pre>
              <form method="post" action="/admin/service/resume?key={e(key)}">
                {_credentials(key, "resume", err)}
                <div class="acts">
                <button style="background:#136f3b;color:#fff;border:0;
                    padding:.7rem 1.4rem;font-size:1rem;border-radius:6px">
                  Put the bot back in service</button>
                </div>
              </form>
              <p><small class="dim">Putting a bot back that was stopped for
              misbehaving is as consequential as stopping it, so it takes the
              same two credentials.</small></p>
            </div>"""
        else:
            body = f"""
            <div style="border:1px solid #ccc;padding:1.25rem;border-radius:8px">
              <h2 style="margin-top:0">The bot is in service</h2>
              <p>Use this only if the bot is doing something wrong and you
                 need it to stop <em>now</em>. It keeps answering — with a
                 maintenance notice — so the page on the library site does not
                 break.</p>
              <form method="post" action="/admin/service/pause?key={e(key)}">
                {_credentials(key, "pause", err)}
                <label for="op-note">Why (optional, for the log)</label>
                <input id="op-note" name="note" style="max-width:36rem">
                <div class="acts">
                <button style="background:#b61e2e;color:#fff;border:0;
                    padding:.7rem 1.4rem;font-size:1rem;border-radius:6px">
                  Take the bot out of service</button>
                </div>
              </form>
            </div>"""
        return page("Service control", body, current="/admin/service", key=key)

    @router.get("/service", response_class=HTMLResponse)
    async def service_page(key: str = "", _u=Depends(guard)):
        return HTMLResponse(_page(key))

    @router.post("/service/pause", response_class=HTMLResponse)
    async def do_pause(key: str = "", email: str = Form(""),
                       password: str = Form(""), note: str = Form(""),
                       _u=Depends(guard)):
        why = check_operator(email, password)
        if why:
            # Never echo the passphrase, not even to say it was wrong.
            logger.warning("service pause REFUSED for %r: %s",
                           (email or "").strip().lower(), why)
            return HTMLResponse(_page(key, why), status_code=403)
        pause(who=(email or "").strip().lower(), note=note)
        return RedirectResponse(f"/admin/service?key={key}", status_code=303)

    @router.post("/service/resume", response_class=HTMLResponse)
    async def do_resume(key: str = "", email: str = Form(""),
                        password: str = Form(""), _u=Depends(guard)):
        why = check_operator(email, password)
        if why:
            logger.warning("service resume REFUSED for %r: %s",
                           (email or "").strip().lower(), why)
            return HTMLResponse(_page(key, why), status_code=403)
        resume(who=(email or "").strip().lower())
        return RedirectResponse(f"/admin/service?key={key}", status_code=303)

    return router


__all__ = ["PAUSED_MESSAGE", "build_killswitch_router", "is_paused",
           "pause", "pause_reason", "resume"]
