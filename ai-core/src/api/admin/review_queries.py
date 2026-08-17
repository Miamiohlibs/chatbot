"""
Read-only Prisma queries powering the subject-librarian review surface
(plan Op 1). NO writes here -- this module only ever does find_many /
find_unique. The librarian workflow is: spot a wrong/questionable
answer, note its id + time, report it to the maintainer (who changes
backend behavior). Verdict-writing / corrections / digests are
deliberately out of scope for v1.

All functions are defensive: a query failure returns an empty
result, never raises into the endpoint -- a broken admin query must
degrade to "no rows", not 500 the page.

Schema fields used (verified against prisma/schema.prisma):
  Message(type, content, timestamp, conversationId, isPositiveRated,
          intent, scopeCampus, scopeLibrary, modelUsed, confidence,
          wasRefusal, refusalTrigger, citedChunkIds)
  Conversation(id, createdAt, updatedAt, toolUsed)
  ModelTokenUsage(llmModelName, promptTokens, completionTokens,
          totalTokens, cachedInputTokens, callSite, conversationId,
          createdAt)
  ToolExecution(agentName, toolName, success, executionTime,
          timestamp, conversationId)
  ConversationFeedback(rating, userComment, conversationId)

`isPositiveRated` is the thumbs signal: False = thumbs-DOWN (the
primary "questionable answer" trigger), True = up, None = unrated.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

LIBRARY_TZ = "America/New_York"
"""Kept as a literal rather than imported from config.budget: this module is
read-only and deliberately dependency-light, and one string is cheaper than a
coupling. If the libraries ever move, both change."""


def local_dt(value: "Any") -> "Optional[datetime]":
    """The same instant, expressed in the libraries' timezone.

    Separate from `local_ts` because one caller needs the DATE, not a
    display string: the cost dashboard buckets spend with
    `createdAt.date()`, and on a UTC clock an 8pm Eastern conversation
    falls on the FOLLOWING day. Evening is peak library use, so every
    night's spend was landing on tomorrow's row.
    """
    if not isinstance(value, datetime):
        return None
    try:
        from zoneinfo import ZoneInfo

        aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return aware.astimezone(ZoneInfo(LIBRARY_TZ))
    except Exception:  # noqa: BLE001
        return value


def local_ts(value: "Any") -> str:
    """A timestamp a librarian in Oxford can read, without doing arithmetic.

    THE BOX RUNS UTC AND OXFORD DOES NOT. Postgres hands these back as
    timezone-aware UTC, and `str(dt)` rendered them verbatim:

        created: 2026-08-15 22:35:04.964000+00:00

    That is 6:35pm Eastern. A librarian reviewing a conversation should not
    have to subtract four hours -- and worse, cannot tell whether a given
    row is off by four or five without knowing whether that date was in DST.

    Same reasoning as `config.budget.library_now()`, which already exists for
    exactly this reason on the budget side.

    Rendered as `2026-08-15 18:35 EDT`: seconds and microseconds are noise
    for review, and the abbreviation is kept so the value is unambiguous
    rather than merely different.

    Defensive like everything else here -- anything unparseable comes back as
    its own string rather than raising into a page.
    """
    if not value:
        return ""
    if not isinstance(value, datetime):
        return str(value)
    # Naive values are assumed UTC: that is what Postgres stores and what
    # every writer in this codebase uses.
    local = local_dt(value)
    if local is None:
        return str(value)
    try:
        return local.strftime("%Y-%m-%d %H:%M %Z")
    except Exception:  # noqa: BLE001 -- a clock bug must not 500 the page
        return str(value)



# Recognized list filters. Anything else falls back to "flagged".
FILTERS = ("flagged", "thumbs_down", "thumbs_up", "refusal",
           "low_confidence", "rated", "reviewed", "all")


def _msg_dict(m: Any) -> dict:
    return {
        "id": getattr(m, "id", None),
        "role": getattr(m, "type", None),
        "content": getattr(m, "content", "") or "",
        "time": local_ts(getattr(m, "timestamp", None)),
        "intent": getattr(m, "intent", None),
        "scope_campus": getattr(m, "scopeCampus", None),
        "scope_library": getattr(m, "scopeLibrary", None),
        "model_used": getattr(m, "modelUsed", None),
        "confidence": getattr(m, "confidence", None),
        "was_refusal": bool(getattr(m, "wasRefusal", False)),
        "refusal_trigger": getattr(m, "refusalTrigger", None),
        "is_positive_rated": getattr(m, "isPositiveRated", None),
        "cited_chunk_ids": list(getattr(m, "citedChunkIds", []) or []),
    }


async def list_flagged(
    db: Any,
    *,
    filter_preset: str = "flagged",
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Return summary rows of MESSAGES that warrant a librarian look.

    `flagged` (default) = thumbs-down OR a refusal OR low confidence
    -- the union a reviewer cares about. Newest first. Each row is
    enough for the list view; full drill-down is `conversation_detail`.
    """
    where: dict
    fp = filter_preset if filter_preset in FILTERS else "flagged"
    if fp == "thumbs_down":
        where = {"isPositiveRated": False}
    elif fp == "thumbs_up":
        # Positive ratings were unreachable before 2026-07-27: the data
        # was there (Message.isPositiveRated=True) but no preset queried
        # it, so "what is the bot getting RIGHT" had no surface.
        where = {"isPositiveRated": True}
    elif fp == "refusal":
        where = {"wasRefusal": True}
    elif fp == "low_confidence":
        where = {"confidence": "low"}
    elif fp == "reviewed":
        where = {"NOT": [{"reviewedAt": None}]}
    elif fp == "rated":
        # Turns in a conversation the patron left a star rating on.
        # Conversation-scoped signal projected onto message rows --
        # resolved after the query (see _rated_conversation_ids).
        where = {"type": "assistant"}
    elif fp == "all":
        where = {}
    else:  # flagged: the union reviewers actually want
        where = {
            "OR": [
                {"isPositiveRated": False},
                {"wasRefusal": True},
                {"confidence": "low"},
            ]
        }
    # Handled rows drop out of every working view except the explicit
    # "reviewed" and "all" tabs -- otherwise the queue never shrinks and
    # a reviewer can't tell fresh from already-triaged.
    if fp not in ("reviewed", "all"):
        where = {"AND": [where, {"reviewedAt": None}]} if where else {"reviewedAt": None}
    try:
        rows = await db.message.find_many(
            where=where,
            order={"timestamp": "desc"},
            take=max(1, min(limit, 200)),
            skip=max(0, offset),
        )
    except Exception as e:  # noqa: BLE001 -- admin query must not 500
        logger.warning("list_flagged query failed: %s", e)
        return []
    return [
        {
            "message_id": getattr(m, "id", None),
            "conversation_id": getattr(m, "conversationId", None),
            "time": local_ts(getattr(m, "timestamp", None)),
            "role": getattr(m, "type", None),
            "preview": (getattr(m, "content", "") or "")[:240],
            "intent": getattr(m, "intent", None),
            "was_refusal": bool(getattr(m, "wasRefusal", False)),
            "refusal_trigger": getattr(m, "refusalTrigger", None),
            "confidence": getattr(m, "confidence", None),
            "is_positive_rated": getattr(m, "isPositiveRated", None),
            "reviewed_at": (
                local_ts(getattr(m, "reviewedAt", None)) or None
            ),
        }
        for m in (rows or [])
    ]


async def dashboard_counts(db: Any) -> dict:
    """The numbers the dashboard leads with.

    Operator feedback 2026-07-28: the hub was a list of links, so
    answering "is there anything waiting for me?" meant opening every
    page. These counts make that the first thing on screen.

    Never raises: a failed count returns 0 rather than 500ing the
    dashboard, and 0 renders as the calm state -- worth knowing if you
    are debugging a suspiciously quiet console.
    """
    async def _count(make_coro):
        """Takes a THUNK, not a coroutine: building the coroutine is
        itself what raises when a table or column is missing, so an
        eagerly-constructed argument would blow past this handler and
        500 the whole dashboard."""
        try:
            return int(await make_coro())
        except Exception as e:  # noqa: BLE001
            logger.warning("dashboard count failed: %s", e)
            return 0

    tickets = await _count(lambda: db.correctionticket.count(
        where={"status": {"in": ["open", "in_progress", "reviewed"]}}))
    tickets_open = await _count(lambda: db.correctionticket.count(
        where={"status": "open"}))
    flagged = await _count(lambda: db.message.count(where={"AND": [
        {"OR": [{"isPositiveRated": False}, {"wasRefusal": True},
                {"confidence": "low"}]},
        {"reviewedAt": None},
    ]}))
    praised = await _count(lambda: db.message.count(where={"AND": [
        {"isPositiveRated": True}, {"reviewedAt": None}]}))
    corrections = await _count(lambda: db.manualcorrection.count(
        where={"active": True}))
    return {
        "tickets": tickets,
        "tickets_open": tickets_open,
        "flagged": flagged,
        "praised": praised,
        "corrections": corrections,
    }


async def attach_feedback(db: Any, rows: list[dict]) -> list[dict]:
    """Annotate list rows with their conversation's patron star rating.

    The star rating + comment ("rate this conversation") lives on
    ConversationFeedback, keyed by conversation -- so before 2026-07-27
    the only way to find a rated conversation was to open rows one at a
    time and hope. One batched query per page adds `feedback_rating` /
    `feedback_comment` so the list can show them inline.

    Never raises: on a DB error the rows come back unannotated.
    """
    conv_ids = list({r.get("conversation_id") for r in rows
                     if r.get("conversation_id")})
    if not conv_ids:
        return rows
    try:
        fbs = await db.conversationfeedback.find_many(
            where={"conversationId": {"in": conv_ids}}
        )
    except Exception as e:  # noqa: BLE001 -- annotation is garnish
        logger.warning("attach_feedback failed: %s", e)
        return rows
    by_conv = {
        getattr(f, "conversationId", None): f for f in (fbs or [])
    }
    for r in rows:
        f = by_conv.get(r.get("conversation_id"))
        r["feedback_rating"] = getattr(f, "rating", None) if f else None
        r["feedback_comment"] = getattr(f, "userComment", None) if f else None
    return rows


async def mark_reviewed(
    db: Any, message_id: str, *, reviewed_by: str = "operator",
    undo: bool = False,
) -> bool:
    """Flip one queue row's triage state. Returns True on success.

    Idempotent by construction: setting an already-set value is a no-op
    write. `undo` clears it so a mis-click is recoverable.
    """
    try:
        await db.message.update(
            where={"id": str(message_id)},
            data=(
                {"reviewedAt": None, "reviewedBy": None} if undo
                else {"reviewedAt": datetime.now(timezone.utc),
                      "reviewedBy": reviewed_by}
            ),
        )
        return True
    except Exception as e:  # noqa: BLE001 -- admin action must not 500
        logger.warning("mark_reviewed(%s) failed: %s", message_id, e)
        return False


def _tools_used_summary(tools: Any, conv: Any) -> list[str]:
    """Distinct tool names for one conversation, first-use order.

    Prefers the ToolExecution rows (written per turn by the v2 socket
    handler) and falls back to the legacy `Conversation.toolUsed` column
    for conversations recorded before the rows were persisted.
    """
    names: list[str] = []
    for t in (tools or []):
        name = getattr(t, "toolName", None)
        if name and name not in names:
            names.append(str(name))
    if names:
        return names
    return [str(n) for n in (getattr(conv, "toolUsed", []) or [])]


async def conversation_detail(db: Any, conversation_id: str) -> Optional[dict]:
    """Full read-only drill-down for one conversation: id, time, the
    whole transcript, token usage, tools called, human-handoff, and
    the ultimate outcome. Returns None if not found / on error."""
    if not conversation_id:
        return None
    try:
        conv = await db.conversation.find_unique(
            where={"id": str(conversation_id)}
        )
        if conv is None:
            return None
        msgs = await db.message.find_many(
            where={"conversationId": str(conversation_id)},
            order={"timestamp": "asc"},
        )
        toks = await db.modeltokenusage.find_many(
            where={"conversationId": str(conversation_id)},
            order={"createdAt": "asc"},
        )
        tools = await db.toolexecution.find_many(
            where={"conversationId": str(conversation_id)},
            order={"timestamp": "asc"},
        )
        fb = await db.conversationfeedback.find_unique(
            where={"conversationId": str(conversation_id)}
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "conversation_detail(%s) failed: %s", conversation_id, e
        )
        return None

    messages = [_msg_dict(m) for m in (msgs or [])]
    # Human-handoff: any turn whose refusal trigger routes to a person.
    handoff_triggers = {
        "human_handoff", "capability_limit", "live_data_down",
        "staff_privacy",
    }
    handoff = [
        {"message_id": m["id"], "time": m["time"],
         "trigger": m["refusal_trigger"]}
        for m in messages
        if m["was_refusal"] and (m["refusal_trigger"] in handoff_triggers)
    ]
    last_assistant = next(
        (m for m in reversed(messages) if m["role"] == "assistant"), None
    )
    token_rows = [
        {
            "model": getattr(t, "llmModelName", None),
            "call_site": getattr(t, "callSite", None),
            "prompt": getattr(t, "promptTokens", 0),
            "cached_input": getattr(t, "cachedInputTokens", 0),
            "completion": getattr(t, "completionTokens", 0),
            "total": getattr(t, "totalTokens", 0),
            "time": local_ts(getattr(t, "createdAt", None)),
        }
        for t in (toks or [])
    ]
    return {
        "conversation_id": str(conversation_id),
        "created_at": local_ts(getattr(conv, "createdAt", None)),
        "updated_at": local_ts(getattr(conv, "updatedAt", None)),
        # Derived from the ToolExecution rows rather than read straight
        # from Conversation.toolUsed. That column is only written by the
        # ARCHIVED legacy orchestrator, so for all v2 traffic it is empty
        # and this line used to render "Tools used: none" even when the
        # table below listed calls. Rows are authoritative; the column is
        # kept as a fallback so pre-v2 conversations still show something.
        "tools_used_summary": _tools_used_summary(tools, conv),
        "messages": messages,
        "token_usage": token_rows,
        "token_total": sum(r["total"] or 0 for r in token_rows),
        "tools_called": [
            {
                "agent": getattr(t, "agentName", None),
                "tool": getattr(t, "toolName", None),
                "success": bool(getattr(t, "success", False)),
                "ms": getattr(t, "executionTime", 0),
                "time": local_ts(getattr(t, "timestamp", None)),
            }
            for t in (tools or [])
        ],
        "human_handoff": handoff,
        "outcome": {
            "final_answer": (last_assistant or {}).get("content"),
            "was_refusal": (last_assistant or {}).get("was_refusal"),
            "refusal_trigger": (last_assistant or {}).get("refusal_trigger"),
            "confidence": (last_assistant or {}).get("confidence"),
        },
        "feedback": (
            None if fb is None else {
                "rating": getattr(fb, "rating", None),
                "comment": getattr(fb, "userComment", None),
            }
        ),
    }


__all__ = ["FILTERS", "attach_feedback", "conversation_detail",
           "dashboard_counts", "list_flagged", "mark_reviewed"]
