"""`GET /admin/audit` -- who did what, on the surfaces where it matters.

This is the other half of dropping the passphrase. A shared secret typed
into a box was never a record of who acted; it was a record that somebody
who knew the secret acted. Once Miami SSO says which of the five people is
asking, the secret stops earning its place -- but only if what replaces it
is legible to the next person who needs to know what happened.

So the page reads like an answer to "what has been done to the bot
lately?" rather than a dump of a log file: the sentence first, the name
beside it, and an explicit mark on every line the console could not
vouch for.

See src/api/admin/audit.py for what is written and why it is a file.
"""

from __future__ import annotations

import logging
from typing import Any

try:
    from starlette.requests import Request  # type: ignore
except Exception:  # noqa: BLE001
    Request = Any  # type: ignore

from src.api.admin import admin_ui as ui
from src.api.admin import audit
from src.api.admin.review_queries import local_ts

logger = logging.getLogger(__name__)

_NOINDEX = {"X-Robots-Tag": "noindex, nofollow, noarchive"}

# What the filter chips offer. "Everything" first because the common
# question is "what happened lately", not "show me one kind of thing".
_FILTERS = (
    ("", "Everything"),
    ("corpus", "Corpus"),
    ("service", "Service"),
)


def _when(row: dict) -> str:
    """The timestamp in Oxford time.

    Stored in UTC, because a log that renews its own ambiguity twice a year
    is a log you cannot order. Shown in the timezone the reader lives in,
    because they are trying to line it up against something they remember.
    """
    raw = str(row.get("at") or "")
    if not raw:
        return "—"
    try:
        import datetime as dt

        return local_ts(dt.datetime.fromisoformat(raw))
    except Exception:  # noqa: BLE001
        return raw


def _row(r: dict) -> str:
    actor = str(r.get("actor") or "")
    authed = bool(r.get("authenticated"))
    if actor and authed:
        who = f"<b>{ui.e(actor)}</b>"
    elif actor:
        # Typed into a form by somebody holding the shared key. Say so on
        # the line rather than in a footnote -- a name that looks like the
        # others but means something weaker is the one way this page could
        # mislead the person reading it.
        who = (f"{ui.e(actor)} <span class='tag refuse' "
               f"title='Typed into the form by a caller holding the shared "
               f"key. Nobody verified it.'>unverified</span>")
    else:
        who = "<span class='dim'>shared key</span>"

    target = (f"<code>{ui.e(r.get('target'))}</code>"
              if r.get("target") else "")
    detail = (f"<div class='dim' style='margin-top:.15rem'>"
              f"{ui.e(r.get('detail'))}</div>" if r.get("detail") else "")
    ip = f"<span class='dim'>{ui.e(r.get('ip'))}</span>" if r.get("ip") else ""
    return (
        f"<tr><td style='white-space:nowrap'>{ui.e(_when(r))}</td>"
        f"<td>{who}</td>"
        f"<td>{ui.e(audit.describe(r))} {target}{detail}</td>"
        f"<td>{ip}</td></tr>"
    )


def render(key: str, *, kind: str = "", caller=None) -> str:
    rows = audit.read_recent(limit=300)
    if kind:
        rows = [r for r in rows if str(r.get("action") or "").startswith(kind)]

    chips = "".join(
        f"<a class='tag{" active" if kind == val else ""}' "
        f"href='/admin/audit?kind={val}"
        f"{f'&key={ui.e(key)}' if key else ''}'>{ui.e(label)}</a>"
        for val, label in _FILTERS
    )

    if not rows:
        body = ui.empty("Nothing recorded yet. Actions appear here as they "
                        "are taken — approving a corpus rebuild, taking the "
                        "bot out of service.")
    else:
        body = (
            "<div class='scroll-table'><table>"
            "<thead><tr><th>When</th><th>Who</th><th>What</th><th>From</th>"
            "</tr></thead><tbody>"
            + "".join(_row(r) for r in rows)
            + "</tbody></table></div>"
        )

    unverified = sum(1 for r in rows if not r.get("authenticated"))
    note = ""
    if unverified:
        note = (f"<p class='hint'>{unverified} of these were done with the "
                f"shared key rather than a Miami sign-in, so the name on "
                f"them is whatever was typed into the form.</p>")

    return ui.page(
        "Audit log",
        "<h1>Audit log</h1>"
        "<p class='lede'>Every action that changes what the bot does or "
        "whether it answers at all. Read newest first; the last three "
        "months are kept on this page.</p>"
        f"<div class='filter-bar'>{chips}</div>"
        + body + note,
        current="/admin/audit", key=key, who=caller)


def build_audit_router(deps: dict):
    from fastapi import APIRouter, Depends  # type: ignore
    from fastapi.responses import HTMLResponse  # type: ignore

    guard = deps.get("guard")
    router = APIRouter(prefix="/admin", tags=["admin"])

    if guard is None:
        async def guard() -> None:  # noqa: D401 -- mounted only behind one
            return None

    @router.get("/audit", response_class=HTMLResponse)
    async def audit_page(key: str = "", kind: str = "",
                         caller=Depends(guard)):
        # `kind` is matched against a fixed list rather than used as a
        # prefix directly: it reaches a filter, not a file path, but a
        # value from the query string that reaches anything at all is
        # worth pinning to what we offer.
        kind = kind if kind in {v for v, _ in _FILTERS} else ""
        return HTMLResponse(render(key, kind=kind, caller=caller),
                            headers=_NOINDEX)

    return router
