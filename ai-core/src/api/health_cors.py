"""Cross-origin access to /health/ready, and ONLY that one path.

WHY THIS IS SEPARATE FROM THE APP-WIDE CORSMiddleware
    Ken (web services) wants to show chatbot availability on a library
    page -- a `fetch()` from https://www.lib.miamioh.edu (or another
    miamioh.edu subdomain) against /health/ready. That needs CORS.

    The obvious fix is to add miamioh.edu to the existing CORSMiddleware
    origin list. Do not do that. That middleware runs with
    `allow_credentials=True` across the WHOLE app, so widening its origin
    list would let any page on any allowed origin make credentialed
    cross-origin requests to /admin/* and /librarian/* and READ THE
    REPLIES using the visitor's `mu_admin_sso` session cookie. The
    console shows raw patron conversations. That is not a trade worth
    making so a status dot can turn green.

    So this is deliberately narrow:

      * path        -- exactly /health/ready. Not a prefix.
      * credentials -- never. The header is actively REMOVED, because the
                       app-wide middleware sets it and a stale
                       Allow-Credentials next to our Allow-Origin would
                       imply a contract we do not want.
      * methods     -- GET, HEAD, OPTIONS. These endpoints are reads.
      * origins     -- https on miamioh.edu or any subdomain of it.

    ONE path, not the /health/ prefix. Ken asked for /health/ready and
    that is what this opens. The prefix would also have covered /health,
    which fans out to six external probes (Postgres, Weaviate, OpenAI,
    LibCal, LibGuides, LibAnswers) on every call -- a page polling it from
    a browser would be spending our upstream quota on somebody else's
    render loop. /health/ready is already cached behind HEALTH_PROBE_TTL_S.

    If another endpoint genuinely needs opening later, add it to _ALLOWED_PATHS
    deliberately rather than widening this to a prefix.

    Nothing here grants access that did not already exist: /health/ready is
    unauthenticated and anyone can curl it today. CORS governs whether
    BROWSER JAVASCRIPT on another origin may read the response, not
    whether the data is reachable. This adds no new disclosure.

WHY IT MUST BE REGISTERED LAST
    Starlette makes the most recently added middleware the OUTERMOST, and
    CORSMiddleware answers preflight itself -- it returns 400 "Disallowed
    CORS origin" for an origin not on its list. If it saw the OPTIONS
    first, this middleware would never run. Registered last, we handle
    the preflight and short-circuit before it gets there.
"""

from __future__ import annotations

import os
import re

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# https, miamioh.edu or any subdomain. Anchored at both ends: an
# unanchored version matches "https://miamioh.edu.evil.com".
_MIAMI_ORIGIN = re.compile(r"^https://([A-Za-z0-9-]+\.)*miamioh\.edu$")

# Localhost is NOT enabled by NODE_ENV. The production box has
# NODE_ENV=development in its .env, so keying dev origins off it means
# production quietly allows http://localhost:*. Opt in explicitly.
_LOCALHOST_ORIGIN = re.compile(r"^http://(localhost|127\.0\.0\.1)(:\d+)?$")

_ALLOWED_METHODS = "GET, HEAD, OPTIONS"

# An explicit set, not a prefix. Adding to it should be a decision someone
# makes on purpose -- /health alone fans out to six external probes per
# call, and a browser polling loop must not reach it.
_ALLOWED_PATHS = frozenset({"/health/ready"})


def _allow_localhost() -> bool:
    return os.getenv("CORS_ALLOW_LOCALHOST", "").strip().lower() in {
        "1", "true", "yes",
    }


def is_cors_path(path: str) -> bool:
    """Exact match against _ALLOWED_PATHS. A trailing slash is tolerated
    because FastAPI redirects it to the canonical path and the browser
    follows, landing on a response this middleware does decorate."""
    return path.rstrip("/") in _ALLOWED_PATHS or path in _ALLOWED_PATHS


def origin_allowed(origin: str) -> bool:
    if not origin:
        return False
    if _MIAMI_ORIGIN.match(origin):
        return True
    return bool(_allow_localhost() and _LOCALHOST_ORIGIN.match(origin))


def _apply(response: Response, origin: str) -> Response:
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Access-Control-Allow-Methods"] = _ALLOWED_METHODS
    response.headers["Access-Control-Max-Age"] = "600"
    # Caches (and the browser's own) must not serve one origin's response
    # to another. Appended rather than assigned: something upstream may
    # already vary on something else.
    existing = response.headers.get("Vary")
    if existing:
        if "origin" not in existing.lower():
            response.headers["Vary"] = f"{existing}, Origin"
    else:
        response.headers["Vary"] = "Origin"
    # The app-wide middleware sets this; on a public endpoint it is
    # misleading at best. Say what we mean: no credentials here.
    response.headers.pop("Access-Control-Allow-Credentials", None)
    return response


class HealthCorsMiddleware(BaseHTTPMiddleware):
    """CORS for /health/ready only, credential-free. See module docstring."""

    async def dispatch(self, request: Request, call_next):
        if not is_cors_path(request.url.path):
            return await call_next(request)

        origin = request.headers.get("origin", "")

        # Preflight. Answered here so the app-wide CORSMiddleware never
        # gets the chance to reject the origin.
        if request.method == "OPTIONS" and request.headers.get(
            "access-control-request-method"
        ):
            if not origin_allowed(origin):
                # 403 rather than silence: a developer reading devtools
                # should be able to tell "origin refused" from "endpoint
                # down". The body is never read by the browser.
                return Response(status_code=403, content=b"")
            resp = Response(status_code=204, content=b"")
            requested = request.headers.get("access-control-request-headers")
            if requested:
                resp.headers["Access-Control-Allow-Headers"] = requested
            return _apply(resp, origin)

        response = await call_next(request)
        if origin_allowed(origin):
            _apply(response, origin)
        return response
