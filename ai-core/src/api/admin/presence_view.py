""""Is anyone using it right now?" -- the question asked before a deploy.

Rendered on the dashboard and on the service page, which are the two
surfaces somebody is already looking at when they are about to do
something disruptive. The counting, and the reason there are three
numbers rather than one, is in src/api/presence.py.
"""

from __future__ import annotations

from src.api import presence
from src.api.admin import admin_ui as ui

_NOINDEX = {"X-Robots-Tag": "noindex, nofollow, noarchive"}


def render_card(snap: "dict | None" = None, *, key: str = "",
                heading: bool = True) -> str:
    """The three counts and the verdict.

    The verdict leads. The counts are the evidence for it, and somebody
    about to run a deploy wants the answer before the arithmetic.
    """
    snap = presence.snapshot() if snap is None else snap
    cls = "good" if snap["safe_to_restart"] else "warn"

    tiles = "".join([
        _tile(snap["waiting"], "waiting on an answer",
              needs=bool(snap["waiting"])),
        _tile(snap["in_conversation"], "in a conversation",
              needs=bool(snap["in_conversation"])),
        _tile(snap["open"], "widget loaded"),
    ])

    longest = ""
    if snap["waiting"] and snap["longest_wait_s"]:
        longest = (f"<p class='hint'>The longest has been waiting "
                   f"{snap['longest_wait_s']:.0f}s.</p>")

    head = ("<h2>Anyone using it right now?</h2>" if heading else "")
    return (
        f"{head}"
        f"<div class='card'>"
        f"<p class='{cls}'>{ui.e(snap['verdict'])}</p>"
        f"<div class='stats' style='margin:.9rem 0 0'>{tiles}</div>"
        f"{longest}"
        f"<p class='hint' style='margin-bottom:0'>"
        f"&ldquo;In a conversation&rdquo; means they have typed something in "
        f"the last {snap['active_window_s'] // 60} minutes. A widget that is "
        f"only loaded reconnects on its own and loses nothing. Counted in "
        f"this process, which is the only one there is."
        f"</p></div>"
    )


def _tile(n: int, label: str, *, needs: bool = False) -> str:
    """Like ui.stat_card but not a link -- there is nowhere to go. A
    number that looks clickable and is not is a small lie every time
    somebody clicks it."""
    cls = "stat needs" if needs else "stat calm"
    return (f"<div class='{cls}'>"
            f"<div class='lbl'>{ui.e(label)}</div>"
            f"<div class='n'>{ui.e(n)}</div></div>")


def build_presence_router(deps: dict):
    """`GET /admin/presence.json` -- the same numbers, for a script.

    The page answers the question when somebody remembers to look. The
    deploy runs from a terminal, so the number has to be reachable from
    one:

        curl -s "$BASE/admin/presence.json?key=$ADMIN_API_TOKEN" \\
          | jq -e '.safe_to_restart' >/dev/null || echo "somebody is mid-answer"
    """
    from fastapi import APIRouter, Depends  # type: ignore

    guard = deps.get("guard")
    router = APIRouter(prefix="/admin", tags=["admin"])

    if guard is None:
        async def guard() -> None:  # noqa: D401 -- mounted only behind one
            return None

    @router.get("/presence.json")
    async def presence_json(_c=Depends(guard)):
        return presence.snapshot()

    return router
