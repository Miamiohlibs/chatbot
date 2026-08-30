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
    `ai-core/data/SERVICE_PAUSED` on disk, not a variable (note the
    `ai-core/` -- it is NOT `/opt/chatbot/data/`, which is where an operator
    standing in the repo root will look first):
      * it SURVIVES a restart -- if the bot is paused because it is
        misbehaving, a crash-restart must not quietly put it back in service
      * it can be set or cleared without this router, by touching or deleting
        the file, so a stuck web surface never leaves the operator without a
        way out
      * every worker sees the same state, which a per-process variable would
        not guarantee

DELIBERATELY NOT BEHIND SSO (2026-08-21)
    Every other /admin surface now requires a Miami SSO session. This one
    does not, and that is the point of it.

    The lever that stops a misbehaving bot must not depend on the thing most
    likely to be broken at the same time. An IdP outage, an expired
    certificate, a mistyped uid, a release policy that stops sending the
    attribute -- any one of those would, if this page sat behind SSO, leave
    the bot answering patrons with nobody able to stop it. A shutdown
    control that is unreachable during an incident is not a shutdown
    control.

    So it is mounted on its own, independent of `ADMIN_API_TOKEN`, of
    `SSO_ENABLED`, and of the IdP being reachable at all. What protects it
    is the second factor below, which is self-contained: an operator email
    from a fixed list plus a shared passphrase, both read from .env, neither
    requiring any network call.

    The page being reachable is not the same as the switch being usable.
    Without the email and the passphrase a visitor sees a form and a status
    that `/health/service` already publishes to the world.

SECOND FACTOR ON THE SWITCH ITSELF
    Operator ruling 2026-08-10: the token alone is too easy. Taking the bot
    out of service -- or putting it BACK, which matters just as much when it
    is out because it is misbehaving -- also needs an operator email from
    `SERVICE_PAUSE_OPERATORS` and the shared passphrase in
    `SERVICE_PAUSE_PASSWORD`. Both live in .env and never in this repo.

    Be clear about what that buys, because it is easy to overrate: the email
    is TYPED, not proven. Anyone holding the passphrase can enter any name
    on the list -- and since 2026-08-21 the passphrase is the ONLY thing
    standing here, because the admin guard was deliberately removed. What it
    gives is a deliberate-action speed bump, an accountability record of who
    says they did it, and a restriction to a known set of people.

    That is a real trade, made with open eyes. Proven identity would mean
    SSO, and SSO is precisely what this control must keep working without.
    The compensating controls are the throttle above, the fact that the
    passphrase is never echoed or hinted at, and that every attempt --
    accepted or refused -- lands in the log with the address it came from.

    Unconfigured means NOBODY can switch the service from the web page. That
    is safe rather than reckless only because the flag is a file: an
    operator with a shell can still `touch ai-core/data/SERVICE_PAUSED` during an
    incident (see above). Keep that escape hatch working.
"""

from __future__ import annotations

import datetime as dt
import hmac
import logging
import os
from pathlib import Path
from typing import Optional

# Module level, NOT inside build_killswitch_router: `from __future__ import
# annotations` makes every annotation a string, and FastAPI resolves those
# against module globals. A Request imported inside the factory is invisible
# there, so FastAPI treated `request: Request` as a request BODY and every
# POST came back 422.
try:  # pragma: no cover - FastAPI is always present in production
    from fastapi import Request
except ImportError:  # pragma: no cover
    Request = object  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

# Taking this page out from behind the admin guard (2026-08-21) removed the
# layer that used to make guessing the passphrase impractical, so the
# throttle has to be put back here rather than assumed. Five wrong answers
# per address per ten minutes: generous for somebody fat-fingering their own
# passphrase under pressure, useless for guessing one.
#
# Only FAILURES are counted. A correct credential pair costs nothing, so an
# operator toggling the service during a real incident is never throttled.
from src.api.admin import audit  # noqa: E402
from src.api.rate_limit import SlidingWindowLimiter  # noqa: E402

_ATTEMPT_MAX = int(os.getenv("SERVICE_PAUSE_ATTEMPT_MAX", "5") or 5)
_ATTEMPT_WINDOW_S = int(os.getenv("SERVICE_PAUSE_ATTEMPT_WINDOW_S", "600") or 600)
_attempts = SlidingWindowLimiter(_ATTEMPT_MAX, _ATTEMPT_WINDOW_S)


def attempt_key(request) -> str:
    """The address a failed attempt is counted against.

    X-Real-IP, because nginx sets it with proxy_set_header and that REPLACES
    whatever the client sent. X-Forwarded-For is NOT used: it was proven
    forgeable through the real nginx path on 2026-08-12, and a throttle keyed
    on a value the attacker chooses is not a throttle.
    """
    if request is None:
        return "unknown"
    real = (request.headers.get("x-real-ip") or "").strip()
    if real:
        return real
    client = getattr(request, "client", None)
    return getattr(client, "host", None) or "unknown"


def note_failed_attempt(key: str) -> bool:
    """Record a refusal. False once the address is over the limit."""
    return _attempts.allow(key)


def reset_attempts(key: str) -> None:
    _attempts.reset(key)


_FLAG_PATH = Path(
    os.getenv("SERVICE_PAUSE_FLAG",
              str(Path(__file__).resolve().parents[3] / "data" / "SERVICE_PAUSED"))
)

ASK_US_URL = "https://www.lib.miamioh.edu/research/research-support/ask/"
"""Where a patron goes when the bot cannot help. Named because the widget's
out-of-service panel links to it too, and one wrong copy of a URL in two
places is how a maintenance notice ends up pointing at a 404."""

PAUSED_MESSAGE = (
    "The library chatbot is temporarily unavailable for maintenance. "
    f"For help right now, please use Ask Us to reach a librarian: {ASK_US_URL}"
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
                "ai-core/data/SERVICE_PAUSED flag file.")
    if not secret:
        return ("SERVICE_PAUSE_PASSWORD is not set, so nobody is authorised "
                "here. An operator with a shell can still touch the "
                "ai-core/data/SERVICE_PAUSED flag file.")

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


def paused_since() -> str:
    """The `paused_at` stamp from the flag file, or "" if unreadable.

    Only the timestamp. `paused_by` is an operator's email and this feeds a
    PUBLIC endpoint -- who took the bot down is an internal accountability
    record, not something to hand to every visitor.
    """
    for line in pause_reason().splitlines():
        if line.startswith("paused_at:"):
            return line.split(":", 1)[1].strip()
    return ""


def build_service_status_router():
    """`GET /health/service` -- is the bot in service? Public, unauthenticated.

    WHY THIS IS SEPARATE FROM THE ADMIN ROUTER
        The admin router is mounted only when ADMIN_API_TOKEN is set. The
        widget needs to know the bot is out of service whether or not the
        admin surface happens to be configured, so this mounts on its own
        and behind no guard.

    WHY IT IS PUBLIC
        Operator, 2026-08-13: "when the bot has been shut down, a user cannot
        be expected to send a message to find out". Before this, the ONLY
        signal was the maintenance reply -- so the launcher looked healthy,
        the three buttons looked live, and a patron learned the bot was down
        by typing a question and waiting for the answer. The widget now polls
        this and says so up front.

        Nothing here is sensitive: that the bot is in maintenance is exactly
        what we want patrons to see. The operator email in the flag file is
        deliberately not included -- see `paused_since`.

    WHY IT LIVES UNDER /health
        nginx already proxies `location /health` to the backend, so this
        works on the live site without an nginx change. Adding a `location`
        block means an nginx edit and reload on launch day; this does not.

    COST
        `is_paused()` is one stat call. Safe to poll.
    """
    from fastapi import APIRouter  # type: ignore

    router = APIRouter(tags=["ops"])

    @router.get("/health/service")
    async def service_status() -> dict:
        paused = is_paused()
        return {
            # `in_service` as well as `paused` so a client that misses the
            # field entirely (old cached bundle, a proxy that mangles it)
            # cannot silently read absence as "paused" and hide a working bot.
            "in_service": not paused,
            "paused": paused,
            "since": paused_since() if paused else None,
            "message": PAUSED_MESSAGE if paused else None,
            "ask_us_url": ASK_US_URL,
        }

    return router


def _operator_for(caller, email: str, password: str):
    """(the address to record, the reason this may not proceed).

    Same rule as the corpus gate: a caller Miami has already identified is
    not asked for a shared secret as well, and one arriving cold is. The
    difference matters more here than anywhere else, because this page is
    deliberately reachable with no credentials -- see make_caller_reader.
    An anonymous caller is exactly who the passphrase was written for.
    """
    if getattr(caller, "authenticated", False):
        uid = (caller.uid or "").strip().lower()
        return (uid if "@" in uid else f"{uid}@miamioh.edu"), None
    return (email or "").strip().lower(), check_operator(email, password)


def build_killswitch_router(deps: dict):
    """`deps` may carry a `guard`; without one the page stands alone.

    Standing alone is the normal case since 2026-08-21 -- see the module
    docstring. A guard is still accepted so the router can be mounted behind
    something in a deployment that wants that, and so the existing tests can
    prove the guarded shape still works.
    """
    from fastapi import APIRouter, Depends, Form  # type: ignore
    from fastapi.responses import HTMLResponse, RedirectResponse  # type: ignore

    async def _no_guard() -> None:
        """The switch protects itself with email + passphrase."""
        return None

    # Now that this page answers 200 to anyone, keep it out of search
    # indexes. This host is already being crawled -- amazonbot and
    # binaryedge both appear in the access log -- and a shutdown control
    # showing up in search results invites exactly the traffic the throttle
    # then has to absorb. Set in-app rather than in nginx so it travels with
    # the route.
    _NOINDEX = {"X-Robots-Tag": "noindex, nofollow, noarchive"}

    guard = deps.get("guard") or _no_guard

    async def _nobody():
        """No caller reader wired up: everybody is anonymous, which is the
        shape this page has always had and the one the passphrase was
        written for."""
        return None

    # NOT a guard. This page stays reachable with no credentials because it
    # has to work when Miami's IdP is the thing that is broken -- guarding
    # the stop button with SSO means an outage takes away the control you
    # reach for during an outage. Reading the session only decides whether
    # the passphrase is still worth asking for.
    peek = deps.get("whoami") or _nobody
    router = APIRouter(prefix="/admin", tags=["admin"])

    def _credentials(key: str, action: str, extra: str = "",
                     caller=None) -> str:
        """The email + passphrase pair -- unless the session already
        settled who this is, in which case asking for a shared secret is
        asking a second time for something Miami already established."""
        from src.api.admin.admin_ui import e

        if getattr(caller, "authenticated", False):
            return f"""
              {extra}
              <p class="hint">Acting as <code>{e(caller.uid)}</code>. This is
              recorded in the audit log.</p>"""
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

    def _page(key: str, error: str = "", caller=None) -> str:
        from src.api.admin.admin_ui import e, page

        paused = is_paused()
        err = (f"<div class='warn' role='alert'>{e(error)}</div>"
               if error else "")
        if paused:
            body = f"""
            <h1>Service control</h1>
            <div class="banner down">
              <b>The bot is OUT OF SERVICE</b>
              Every question is being answered with a maintenance notice
              pointing patrons at Ask Us. The widget still loads &mdash;
              nobody sees a broken page.
            </div>
            <div class="card">
              <pre>{e(pause_reason())}</pre>
              <form method="post" action="/admin/service/resume?key={e(key)}">
                {_credentials(key, "resume", err, caller)}
                <div class="acts">
                  <button type="submit">Put the bot back in service</button>
                </div>
              </form>
              <p class="hint" style="margin-bottom:0">Putting a bot back that
              was stopped for misbehaving is as consequential as stopping it,
              so it takes the same credentials.</p>
            </div>"""
        else:
            body = f"""
            <h1>Service control</h1>
            <p class="lede">The bot is in service. Use this only if it is
               doing something wrong and you need it to stop <em>now</em>.</p>
            <div class="card">
              <p>It keeps answering &mdash; with a maintenance notice &mdash;
                 so the page on the library site does not break.</p>
              <form method="post" action="/admin/service/pause?key={e(key)}">
                {_credentials(key, "pause", err, caller)}
                <label for="op-note">Why (optional, for the log)</label>
                <input id="op-note" name="note" style="max-width:36rem">
                <div class="acts">
                  <button type="submit" class="danger">Take the bot out of
                    service</button>
                </div>
              </form>
            </div>"""
        return page("Service control", body, current="/admin/service",
                    key=key, who=caller)

    @router.get("/service", response_class=HTMLResponse)
    async def service_page(key: str = "", caller=Depends(peek), _u=Depends(guard)):
        return HTMLResponse(_page(key, caller=caller), headers=_NOINDEX)

    @router.post("/service/pause", response_class=HTMLResponse)
    async def do_pause(request: Request, key: str = "", email: str = Form(""),
                       password: str = Form(""), note: str = Form(""),
                       caller=Depends(peek), _u=Depends(guard)):
        actor, why = _operator_for(caller, email, password)
        if why:
            # Never echo the passphrase, not even to say it was wrong.
            logger.warning("service pause REFUSED for %r: %s",
                           (email or "").strip().lower(), why)
            if not note_failed_attempt(attempt_key(request)):
                logger.warning("service pause attempts THROTTLED for %s",
                               attempt_key(request))
                return HTMLResponse(_page(key, _THROTTLED, caller), status_code=429,
                                    headers=_NOINDEX)
            return HTMLResponse(_page(key, why, caller), status_code=403,
                                headers=_NOINDEX)
        reset_attempts(attempt_key(request))
        pause(who=actor, note=note)
        audit.record(audit.SERVICE_PAUSE, who=caller, request=request,
                     detail=(note or "").strip()[:300])
        return RedirectResponse(f"/admin/service?key={key}", status_code=303)

    @router.post("/service/resume", response_class=HTMLResponse)
    async def do_resume(request: Request, key: str = "", email: str = Form(""),
                        password: str = Form(""), caller=Depends(peek), _u=Depends(guard)):
        actor, why = _operator_for(caller, email, password)
        if why:
            logger.warning("service resume REFUSED for %r: %s",
                           (email or "").strip().lower(), why)
            if not note_failed_attempt(attempt_key(request)):
                logger.warning("service resume attempts THROTTLED for %s",
                               attempt_key(request))
                return HTMLResponse(_page(key, _THROTTLED, caller), status_code=429,
                                    headers=_NOINDEX)
            return HTMLResponse(_page(key, why, caller), status_code=403,
                                headers=_NOINDEX)
        reset_attempts(attempt_key(request))
        resume(who=actor)
        audit.record(audit.SERVICE_RESUME, who=caller, request=request)
        return RedirectResponse(f"/admin/service?key={key}", status_code=303)

    return router


_THROTTLED = ("Too many failed attempts from this address. Wait a few "
              "minutes and try again. If the bot must be stopped NOW and "
              "you cannot get in, touch the file "
              "ai-core/data/SERVICE_PAUSED on the server -- that is the "
              "same switch, and it needs no web page at all.")

__all__ = ["ASK_US_URL", "PAUSED_MESSAGE", "attempt_key",
           "build_killswitch_router",
           "build_service_status_router", "is_paused", "pause", "pause_reason",
           "note_failed_attempt", "paused_since", "reset_attempts", "resume"]
