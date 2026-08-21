"""SAML SP endpoints and the admin guard that consumes them.

FOUR ROUTES, ALL UNDER /admin/sso/
    metadata  -- the XML Miami IT needs in order to configure their end.
                 Public on purpose: it contains no secret, and IT asking for
                 a URL is less error-prone than emailing a file around.
    login     -- builds the AuthnRequest and redirects to muidp.
    acs       -- where the IdP POSTs the signed assertion back.
    logout    -- drops the local session cookie.

WHY THE GUARD REDIRECTS INSTEAD OF 401-ING
    These are pages a librarian opens in a browser. A bare 401 is a dead end
    that reads as "broken"; a redirect to the IdP is the behaviour every
    other Miami service has trained them to expect. JSON callers still get a
    401, because a redirect to an HTML login page is useless to a script and
    silently turns a failed API call into a 200 full of markup.
"""

from __future__ import annotations

import logging
from typing import Any

# Module level, NOT inside make_admin_guard. `from __future__ import
# annotations` above makes every annotation a string, and FastAPI resolves a
# dependency's annotations against its MODULE globals. A Request imported
# inside the factory is invisible there, so FastAPI treated `request:
# Request` as a request body and returned 422 for every guarded admin page.
#
# This shipped to production on 2026-08-21 and broke /admin/review,
# /admin/cost, /admin/corrections/view and /admin/tickets/view. The unit
# tests missed it because they call the guard directly with a stub, which
# never exercises FastAPI's dependency resolution -- see
# test_guard_through_a_real_app in test_sso.py, which does.
try:  # pragma: no cover - FastAPI is always present in production
    from fastapi import Request as _FastAPIRequest
except ImportError:  # pragma: no cover
    _FastAPIRequest = object  # type: ignore[assignment,misc]

Request = _FastAPIRequest

from src.api.admin.sso import (
    COOKIE_PATH,
    SESSION_COOKIE,
    SSOConfig,
    display_name_from_attributes,
    is_allowed,
    issue_session,
    read_session,
    safe_next,
    saml_settings,
    uid_from_attributes,
)

logger = logging.getLogger(__name__)


def _saml_request(request: Any) -> dict:
    """Translate a Starlette request into the shape python3-saml wants.

    `https` is read from X-Forwarded-Proto first because uvicorn sits behind
    nginx and sees plain http on 8081. Getting this wrong makes the SP
    advertise http:// URLs, which the IdP then rejects as a Destination
    mismatch -- a failure that reads as "SSO is broken" rather than "one
    header was missed".
    """
    fwd_proto = request.headers.get("x-forwarded-proto", "")
    scheme = fwd_proto or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    return {
        "https": "on" if scheme == "https" else "off",
        "http_host": host.split(":")[0],
        "server_port": "443" if scheme == "https" else "80",
        "script_name": request.url.path,
        "get_data": dict(request.query_params),
        "post_data": {},
    }


def build_sso_router(cfg: SSOConfig) -> Any:
    try:
        from fastapi import APIRouter, Request  # type: ignore
        from fastapi.responses import (  # type: ignore
            HTMLResponse,
            PlainTextResponse,
            RedirectResponse,
            Response,
        )
    except ImportError:  # pragma: no cover -- FastAPI always present in prod
        class _P:
            prefix = "/admin/sso"
            routes: list = []
        return _P()

    router = APIRouter(prefix="/admin/sso", tags=["admin", "sso"])

    def _auth(request: Request, post_data: dict | None = None):
        from onelogin.saml2.auth import OneLogin_Saml2_Auth  # noqa: WPS433

        req = _saml_request(request)
        if post_data is not None:
            req["post_data"] = post_data
        return OneLogin_Saml2_Auth(req, saml_settings(cfg))

    @router.get("/metadata")
    async def metadata() -> Response:
        from onelogin.saml2.settings import OneLogin_Saml2_Settings  # noqa: WPS433

        settings = OneLogin_Saml2_Settings(saml_settings(cfg), sp_validation_only=True)
        xml = settings.get_sp_metadata()
        errors = settings.validate_metadata(xml)
        if errors:
            logger.error("SP metadata is invalid: %s", errors)
            return PlainTextResponse(
                "SP metadata is not valid yet: " + "; ".join(errors),
                status_code=500,
            )
        return Response(content=xml, media_type="application/samlmetadata+xml")

    @router.get("/login")
    async def login(request: Request) -> Response:
        problems = cfg.problems()
        if problems:
            logger.error("SSO login attempted with bad config: %s", problems)
            return PlainTextResponse(
                "Single sign-on is not configured yet:\n  - "
                + "\n  - ".join(problems),
                status_code=503,
            )
        target = safe_next(request.query_params.get("next"))
        auth = _auth(request)
        return RedirectResponse(auth.login(return_to=target), status_code=302)

    @router.post("/acs")
    async def acs(request: Request) -> Response:
        form = await request.form()
        post_data = {k: str(v) for k, v in form.items()}
        auth = _auth(request, post_data)
        auth.process_response()
        errors = auth.get_errors()
        if errors:
            # The reason is logged, never shown. "Signature validation
            # failed" on screen tells an attacker which knob to turn next.
            logger.warning("SAML assertion rejected: %s | %s",
                           errors, auth.get_last_error_reason())
            return HTMLResponse(_denied_page(
                "Sign-in could not be completed.",
                "The response from Miami's login service could not be "
                "verified. Try again; if it keeps happening, the operator "
                "has the details in the service log."), status_code=403)

        attrs = auth.get_attributes() or {}
        uid = uid_from_attributes(attrs)
        if not uid:
            logger.warning("SAML assertion carried no uid/eppn/mail; "
                           "attributes released: %s", sorted(attrs))
            return HTMLResponse(_denied_page(
                "Sign-in succeeded, but we could not read your username.",
                "Miami's login service did not release a uid for this "
                "account. The operator needs to ask IT to release the uid "
                "attribute to this service."), status_code=403)

        if not is_allowed(uid, cfg):
            # Logged at INFO, not WARNING: a colleague clicking a link they
            # were sent is ordinary, not an incident.
            logger.info("SSO sign-in refused for uid=%s (not on the list)", uid)
            return HTMLResponse(_denied_page(
                "You are signed in, but this dashboard is restricted.",
                f"The account <b>{uid}</b> is not on the access list for the "
                "chatbot dashboard. If you need access, ask the operator to "
                "add you."), status_code=403)

        # RelayState rides back in the POST body -- it is what `login()` put
        # there, echoed by the IdP. `safe_next` still vets it, because the
        # IdP is trusted to sign assertions, not to have preserved a value
        # somebody else could have influenced on the way out.
        target = safe_next(post_data.get("RelayState"))
        name = display_name_from_attributes(attrs)
        logger.info("SSO sign-in: uid=%s%s", uid, f" ({name})" if name else "")

        resp = RedirectResponse(target, status_code=303)
        resp.set_cookie(
            SESSION_COOKIE,
            issue_session(uid, cfg),
            max_age=cfg.session_hours * 3600,
            path=COOKIE_PATH,
            httponly=True,
            secure=True,
            samesite="lax",
        )
        return resp

    @router.get("/logout")
    async def logout() -> Response:
        resp = HTMLResponse(_denied_page(
            "Signed out.",
            'You are signed out of the chatbot dashboard. '
            '<a href="/admin/sso/login">Sign in again</a>.'))
        resp.delete_cookie(SESSION_COOKIE, path=COOKIE_PATH)
        return resp

    @router.get("/whoami")
    async def whoami(request: Request) -> dict:
        uid = read_session(request.cookies.get(SESSION_COOKIE), cfg)
        return {"uid": uid, "signed_in": bool(uid)}

    return router


def _denied_page(title: str, body_html: str) -> str:
    """A plain, self-contained page. No shared UI import, because this has to
    render even when the rest of the admin app is unreachable."""
    return (
        "<!doctype html><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{title}</title>"
        "<style>body{font:16px/1.6 system-ui,sans-serif;max-width:34rem;"
        "margin:12vh auto;padding:0 1.2rem;color:#17161A;background:#FBFAF8}"
        "h1{font-size:1.35rem;margin:0 0 .6rem}p{color:#55515A}"
        "a{color:#A8172B}"
        "@media(prefers-color-scheme:dark){body{background:#141316;color:#EDEAE4}"
        "p{color:#9B959D}a{color:#E8697C}}</style>"
        f"<h1>{title}</h1><p>{body_html}</p>"
    )


# --- the guard every admin router depends on -------------------------------


def make_admin_guard(*, cfg: SSOConfig, token: str = ""):
    """FastAPI dependency: allow an SSO session, or the shared token while
    the fallback is still on. Fail-closed in every other case.

    Both keys are checked on every request rather than one being chosen at
    startup, so switching the fallback off is a restart, not a redeploy, and
    switching it back on during an incident is the same.
    """
    from fastapi import HTTPException  # type: ignore

    async def guard(request: Request) -> None:
        if cfg.enabled:
            uid = read_session(request.cookies.get(SESSION_COOKIE), cfg)
            if uid:
                return

        if token and cfg.allow_token_fallback:
            supplied = (
                request.headers.get("x-admin-token")
                or request.query_params.get("key")
                or ""
            )
            if supplied == token:
                return

        if not cfg.enabled:
            # SSO off and the token did not match: nothing else to offer.
            raise HTTPException(status_code=401, detail="admin auth required")

        wants_html = "text/html" in (request.headers.get("accept") or "")
        if wants_html:
            nxt = request.url.path
            if request.url.query:
                nxt = f"{nxt}?{request.url.query}"
            from urllib.parse import quote
            raise HTTPException(
                status_code=307,
                detail="sign-in required",
                headers={"Location": f"/admin/sso/login?next={quote(nxt, safe='')}"},
            )
        raise HTTPException(status_code=401, detail="admin auth required")

    return guard


__all__ = ["build_sso_router", "make_admin_guard"]
