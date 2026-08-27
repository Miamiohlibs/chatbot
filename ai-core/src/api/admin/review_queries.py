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
          wasRefusal, refusalTrigger, citedChunkIds, citedUrls)
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
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

LIBRARY_TZ = "America/New_York"

# The bot went live to the public at 6:00pm Oxford time on 13 August 2026.
# Everything before that instant is development and staff rehearsal, and
# mixing it into the same lists makes "what happened during the beta" a
# question nobody can answer from the screen -- 13 August alone carried 88
# pre-launch conversations against 5 after.
#
# The data is untouched; only the operator views start here.
BETA_START_LOCAL = "2026-08-13T18:00:00"
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
        # The links the patron saw, in citation order. See the schema note:
        # for most turns this is the ONLY record of where we sent someone.
        "cited_urls": list(getattr(m, "citedUrls", []) or []),
    }


def flagged_where(filter_preset: str) -> dict:
    """The Prisma `where` for one preset.

    Extracted so the list and its COUNT cannot drift apart -- a paginated
    view whose total is computed from a different filter than its rows
    tells the operator there are more pages than exist, or fewer.
    """
    where: dict
    fp = filter_preset if filter_preset in FILTERS else "flagged"
    if fp == "thumbs_down":
        where = {"isPositiveRated": False}
    elif fp == "thumbs_up":
        where = {"isPositiveRated": True}
    elif fp == "refusal":
        where = {"wasRefusal": True}
    elif fp == "low_confidence":
        where = {"confidence": "low"}
    elif fp == "reviewed":
        where = {"NOT": [{"reviewedAt": None}]}
    elif fp == "rated":
        where = {"type": "assistant"}
    elif fp == "all":
        where = {}
    else:
        where = {"OR": [{"isPositiveRated": False}, {"wasRefusal": True},
                        {"confidence": "low"}]}
    # Handled rows drop out of every working view except the explicit
    # "reviewed" and "all" tabs -- otherwise the queue never shrinks and a
    # reviewer cannot tell fresh from already-triaged.
    if fp not in ("reviewed", "all"):
        where = ({"AND": [where, {"reviewedAt": None}]} if where
                 else {"reviewedAt": None})
    return where


async def count_flagged(db: Any, *, filter_preset: str = "flagged") -> int:
    """How many rows this preset has in total. 0 on any error."""
    try:
        return int(await db.message.count(where=flagged_where(filter_preset)))
    except Exception:  # noqa: BLE001 -- a missing total must not 500 the page
        return 0


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
    where = flagged_where(filter_preset)
    fp = filter_preset if filter_preset in FILTERS else "flagged"
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


SOURCE_TAGS = (
    ("", "All"),
    ("patron", "Unlabelled"),
    ("patron-confirmed", "Confirmed patron"),
    ("staff", "Staff test"),
    ("maybe-staff", "Possibly staff"),
    ("local", "Local test"),
)


MAX_DAY_SPAN = 31
"""Widest range the day list will read at once.

The whole day's messages are pulled and grouped in Python, so a span is a
scan. A month is enough to answer "what went wrong this term so far" and
small enough that nobody waits; asking for more is clamped and SAID, not
silently trimmed.
"""


async def list_conversations_on(db: Any, day: "str", *,
                                limit: int = 50,
                                offset: int = 0,
                                source: str = "",
                                day_to: str = "",
                                needs_only: bool = False) -> dict:
    """Every conversation that had a question on `day` (YYYY-MM-DD, Oxford time).

    WHY THIS EXISTS
        Until now the only way to see a day's traffic was /admin/review with
        the `all` preset, which lists MESSAGES of every type, newest first,
        across all time -- so "what did people ask today" meant scrolling a
        mixed feed and eyeballing timestamps. This answers the question
        directly.

    OXFORD TIME, NOT UTC
        The window is built in the library's timezone and converted, because
        a day boundary at UTC midnight cuts Oxford's evening in half -- and
        evening is when the building is busiest. `local_dt` carries the same
        note for the cost dashboard, which had exactly this bug.

    Conversations with no user message are skipped: the widget opens a
    socket on page load, so most rows are somebody who never typed anything
    and would otherwise drown the ones who did.

    Returns {rows, total, offset, limit} rather than a bare list, because a
    page that shows 50 of something without saying how many there are is a
    page that quietly hides the rest.
    """
    from datetime import date as _date
    from datetime import timedelta as _td

    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(LIBRARY_TZ)
        y, m, d = (int(p) for p in str(day).split("-"))
        start_local = datetime(y, m, d, tzinfo=tz)

        # A range, when one is asked for. `day_to` is INCLUSIVE -- an
        # operator picking 1st to 7th means seven days, and an end-exclusive
        # reading of that silently drops the day they were looking for.
        end_day = str(day_to or day)
        y2, m2, d2 = (int(p) for p in end_day.split("-"))
        end_local = datetime(y2, m2, d2, tzinfo=tz) + _td(days=1)
        if end_local <= start_local:
            end_local = start_local + _td(days=1)
        clamped = False
        if (end_local - start_local).days > MAX_DAY_SPAN:
            end_local = start_local + _td(days=MAX_DAY_SPAN)
            clamped = True
        start = start_local.astimezone(timezone.utc)
        end = end_local.astimezone(timezone.utc)

        # Clamp to the launch instant. On 13 August this trims the day to
        # its last six hours; on every later day it changes nothing.
        beta = datetime.fromisoformat(BETA_START_LOCAL).replace(
            tzinfo=tz).astimezone(timezone.utc)
        if end <= beta:
            return {"rows": [], "total": 0, "offset": offset, "limit": limit,
                    "source_counts": {}, "before_beta": True,
                    "clamped": False}
        start = max(start, beta)
    except Exception:  # noqa: BLE001 -- a bad date must not 500 the page
        return {"rows": [], "total": 0, "offset": offset, "limit": limit,
                "source_counts": {}, "clamped": False}

    try:
        msgs = await db.message.find_many(
            where={"timestamp": {"gte": start, "lt": end}},
            order={"timestamp": "asc"},
        )
    except Exception:  # noqa: BLE001
        return {"rows": [], "total": 0, "offset": offset, "limit": limit,
                "source_counts": {}, "clamped": clamped}

    by_conv: dict = {}
    for m in msgs:
        cid = getattr(m, "conversationId", None)
        if not cid:
            continue
        slot = by_conv.setdefault(cid, {
            "conversation_id": cid, "first_ts": None, "last_ts": None,
            "questions": [], "question_times": [], "turns": 0,
            "refusals": 0, "thumbs_down": 0, "thumbs_up": 0,
            "low_confidence": 0, "has_dev_row": False,
        })
        ts = getattr(m, "timestamp", None)
        if slot["first_ts"] is None:
            slot["first_ts"] = ts
        slot["last_ts"] = ts
        if getattr(m, "type", "") == "user":
            slot["questions"].append(getattr(m, "content", "") or "")
            slot["question_times"].append(ts)
        else:
            slot["turns"] += 1
            if getattr(m, "wasRefusal", False):
                slot["refusals"] += 1
            if getattr(m, "isPositiveRated", None) is False:
                slot["thumbs_down"] += 1
            elif getattr(m, "isPositiveRated", None) is True:
                slot["thumbs_up"] += 1
            if getattr(m, "confidence", "") == "low":
                slot["low_confidence"] += 1

    out = [v for v in by_conv.values() if v["questions"]]

    # One query for the whole day rather than one per conversation: this
    # runs on every page load and the box has 4GB.
    try:
        usage = await db.modeltokenusage.find_many(
            where={"createdAt": {"gte": start, "lt": end}})
        dev_ids = {u.conversationId for u in usage
                   if "dev" in (getattr(u, "callSite", "") or "")}
    except Exception:  # noqa: BLE001
        dev_ids = set()
    try:
        convs = await db.conversation.find_many(
            where={"createdAt": {"gte": start, "lt": end}})
        origins = {c.id: getattr(c, "origin", None) for c in convs}
        overrides = {c.id: (getattr(c, "sourceOverride", None),
                            getattr(c, "sourceOverrideBy", None))
                     for c in convs}
    except Exception:  # noqa: BLE001
        origins, overrides = {}, {}
    try:
        fbs = await db.conversationfeedback.find_many()
        notes = {f.conversationId: (getattr(f, "userComment", "") or "")
                 for f in fbs}
    except Exception:  # noqa: BLE001
        notes = {}
    for v in out:
        v["has_dev_row"] = v["conversation_id"] in dev_ids
        v["origin"] = origins.get(v["conversation_id"])
        v["feedback_comment"] = notes.get(v["conversation_id"], "")
        ov, ov_by = overrides.get(v["conversation_id"], (None, None))
        v["source_override"] = ov
        v["source_override_by"] = ov_by

    # Run-level signals first: they see what a single row cannot.
    mark_bursts(out)
    mark_repeats(out)
    for v in out:
        v["source"] = classify_source(v)

    # Then the one signal that needs to look outside this day at all. Only
    # for rows nothing has claimed, and only their own question text -- a
    # bounded lookup, not a scan.
    await mark_replays(db, [v for v in out if not v["source"]["label"]])
    for v in out:
        if (v.get("is_replay") or v.get("is_echo")) and not v["source"]["label"]:
            v["source"] = classify_source(v)

    # Counted BEFORE the filter and before paging: a badge on "Staff test"
    # has to say how many staff tests there are that day, not how many are
    # on the page you are looking at.
    source_counts: dict = {"": len(out)}
    for v in out:
        t = v["source"]["tag"]
        key = "patron" if t == "unlabelled" else t
        source_counts[key] = source_counts.get(key, 0) + 1

    if source:
        want = "unlabelled" if source == "patron" else source
        out = [v for v in out if v["source"]["tag"] == want]

    # Only the ones something went wrong in. BEFORE total and paging: a
    # filter applied after them produces a page count for rows the filter
    # already threw away, which reads as a broken pager. This is the same
    # set Flagged shows -- a refusal, a thumbs-down, or a low-confidence
    # answer -- and having it here is what lets one view answer both "what
    # happened today" and "what went wrong this week".
    if needs_only:
        out = [v for v in out
               if v["refusals"] or v["thumbs_down"] or v["low_confidence"]]

    out.sort(key=lambda r: r["first_ts"] or datetime.min.replace(
        tzinfo=timezone.utc), reverse=True)
    total = len(out)
    out = out[offset:offset + limit]
    for r in out:
        r["opened"] = local_ts(r["first_ts"])
        r["opened_hm"] = (local_dt(r["first_ts"]) or datetime.now()).strftime("%H:%M")
        r["asked"] = len(r["questions"])
        r["first_question"] = r["questions"][0]
        r["needs_look"] = bool(r["refusals"] or r["thumbs_down"]
                               or r["low_confidence"])
    return {"rows": out, "total": total, "offset": offset, "limit": limit,
            "source_counts": source_counts, "clamped": clamped}


async def conversation_days(db: Any, *, limit: int = 30) -> list[dict]:
    """Recent days that had at least one question, newest first.

    Powers the date picker. Counting in Python rather than SQL because the
    day boundary has to be Oxford's, and Postgres holds these in UTC.
    """
    try:
        msgs = await db.message.find_many(
            where={"type": "user"}, order={"timestamp": "desc"}, take=4000,
        )
    except Exception:  # noqa: BLE001
        return []
    tally: dict = {}
    for m in msgs:
        ld = local_dt(getattr(m, "timestamp", None))
        if ld is None:
            continue
        tally[ld.date().isoformat()] = tally.get(ld.date().isoformat(), 0) + 1
    return [{"day": d, "questions": n}
            for d, n in sorted(tally.items(), reverse=True)][:limit]


def _norm_q(text: str) -> str:
    """Loose key for 'is this the same question'."""
    import re as _re
    return _re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())


async def find_asks_like(db: Any, question: str, *, limit: int = 25) -> list[dict]:
    """Times this question -- or a close paraphrase -- was actually asked.

    A correction ticket records what a librarian saw once. It says nothing
    about whether one patron hit it or forty did, and that is the difference
    between "worth a note" and "fix this today". Until now finding out meant
    leaving the ticket and searching by hand.

    Matching is deliberately loose and deliberately dumb: exact text first,
    then a contains-search on the longest few words. It is a lead, not a
    measurement -- the page says so.
    """
    q = (question or "").strip()
    if len(q) < 6:
        return []

    seen: dict = {}

    async def _collect(where: dict) -> None:
        try:
            rows = await db.message.find_many(
                where=where, order={"timestamp": "desc"}, take=200)
        except Exception:  # noqa: BLE001 -- a lead is never worth a 500
            return
        for m in rows:
            mid = getattr(m, "id", None)
            if mid in seen:
                continue
            seen[mid] = {
                "conversation_id": getattr(m, "conversationId", ""),
                "content": getattr(m, "content", "") or "",
                "when": local_ts(getattr(m, "timestamp", None)),
                "ts": getattr(m, "timestamp", None),
            }

    await _collect({"type": "user", "content": q})

    # The longest words carry the meaning; stopwords match everything.
    words = sorted(
        (w for w in _norm_q(q).split() if len(w) > 4),
        key=len, reverse=True)[:3]
    for w in words:
        await _collect({"type": "user",
                        "content": {"contains": w, "mode": "insensitive"}})

    out = list(seen.values())
    # Anything sharing a long word is a candidate; rank the ones that share
    # more of the question higher, so the exact repeats float to the top.
    qset = set(_norm_q(q).split())
    for r in out:
        rset = set(_norm_q(r["content"]).split())
        r["overlap"] = len(qset & rset) / max(1, len(qset))
    out.sort(key=lambda r: (-r["overlap"], r["ts"] is None), reverse=False)
    return out[:limit]


# --- where a conversation came from ---------------------------------------
#
# Three states, and the third one is honest rather than embarrassing.
#
#   local     -- a ModelTokenUsage row for this conversation is tagged
#                v2_turn_dev, meaning the request arrived with no browser
#                origin. That is a script. It is a FACT, not a guess.
#   staff?    -- behaves like somebody working through a list rather than
#                somebody with a problem. A READING of the transcript, and
#                labelled as one.
#   (blank)   -- nothing says otherwise. Could be a patron. Could be a
#                colleague on their phone. The system stores no identity,
#                so this is the truthful answer and the UI says so.
#
# Getting this wrong in the direction of "patron" is the dangerous one: it
# inflates every claim about real usage. The heuristics below are therefore
# written to catch obvious testing, not to be clever.

STAFF_MIN_QUESTIONS = 6
STAFF_MAX_MEDIAN_GAP_S = 45.0

# Somebody saying, in the chat, that they are testing. The most reliable
# signal available and the cheapest -- they told us. Two such conversations
# sat unlabelled on 21 August with "this is a staff test" typed into them.
#
# Anchored to the opening of the message so "how do I book a room to take a
# test" is not caught by it.
_SELF_DECLARED = (
    "this is a test", "this is a staff test", "just testing",
    "testing the bot", "test message", "ignore this test",
)

# The same admission, made in the star-rating comment instead of the chat.
# Every comment left on this service so far was one of these: "this is just
# Kevin checking that the bot is up and running!", "demo", and "Students
# might not understand the word 'Reserve'" -- a check, a demo, and an
# evaluator talking about students in the third person. Not one was a
# patron describing their own experience.
_FEEDBACK_TESTING = (
    "checking that the bot", "just checking", "demo", "demoing",
    "this is a test", "testing", "trial run", "students might",
    "students may not", "a student would", "students would",
)


# Phrasing a patron does not use about themselves.
_THIRD_PARTY = (
    "i have a student", "a student who", "professor wanting",
    "patron asked", "someone asked", "hi librarians",
    "a faculty member", "one of our students",
)


# --- testing arrives in runs, not one conversation at a time ---------------
#
# The per-conversation rules miss the commonest shape of testing there is: a
# handful of separate one-question conversations opened seconds apart. Each
# one looks innocent on its own -- somebody asked where the music library is
# -- and only the RUN gives it away. On 17 August a batch like that sat in
# the list with some rows marked "local test" and most unmarked, purely
# because only the turns that reached a language model leave a
# ModelTokenUsage row to read; the ones a fixed rule answered leave nothing.
#
# So the run is classified, not the row. Two signals, both cheap:
#
#   * conversations opening within BURST_GAP_S of each other, in a run of
#     at least BURST_MIN. A person opens one chat window and asks; they do
#     not open five in ninety seconds.
#   * the same question typed again in a different conversation. A patron
#     who got an answer does not re-ask it in a fresh window; somebody
#     checking whether a fix landed does.
#
# Evidence about one member is evidence about the run: if any conversation
# in a burst carries the dev flag, the whole burst was that script.

BURST_GAP_S = 90.0
BURST_MIN = 4

# A script opens conversations about a second and a half apart. A person
# cannot: they have to read the answer, open a new window and type. Measured
# on 21 August against three known runs --
#
#   scripted probe          median gap 1.5s   (min 1.0s)
#   scripted probe, 17 Aug  median gap 1.7s   (min 1.3s)
#   staff testing by hand   median gap 43.0s  (min 7.8s)
#
# -- so five seconds sits in open space between the two, and the separation
# is physical rather than a guess about intent. Without it, a probe that
# happens to send a browser header (as the developer's did) leaves no
# ModelTokenUsage marker and gets read as a person.
SCRIPT_MEDIAN_GAP_S = 5.0

# A verbatim repeat of a long, distinctive question asked on an earlier day
# is a replay, not a coincidence. The developer replayed 206 real questions
# on 19-20 August, and those replays landed in twos and threes -- below the
# burst threshold -- on days after the originals, so neither the burst rule
# nor the same-day repeat rule could see them.
#
# Length is what separates a replay from two people asking the same thing.
# "when do you close" recurs all day and means nothing; forty characters of
# identical text does not happen twice by accident. Measured across the
# whole history: at 12 characters 1,627 conversations look like repeats, at
# 40 it is 609, and the ones it stops claiming are exactly the short common
# questions.
# How far apart two conversations must sit before they belong to separate
# reading windows in sources_for_conversations. Comfortably wider than the
# 10-minute pad on each side, so neighbouring windows do not overlap.
_CLUSTER_SPLIT = timedelta(minutes=30)
# Per-window row cap. Reached only by a genuinely dense window, and reported
# rather than applied silently.
_WINDOW_TAKE = 5000
REPLAY_MIN_CHARS = 40

# A conversation that ORIGINATES nothing. Every question in it was already
# asked, by somebody else, earlier -- so it contributed no new question to
# the record, which is what a replay is and what a person almost never does.
#
# Weaker per-question than REPLAY_MIN_CHARS on purpose: the strength comes
# from ALL of them being second-hand, not from any one being distinctive. A
# floor still applies so a conversation consisting of "hi" is not condemned
# for being unoriginal.
#
# Twenty, not fifteen. At fifteen the rule claimed a second person asking
# "when do you close" (17 characters) -- two patrons wanting the same
# ordinary thing, read as a machine. Twenty keeps the probe questions that
# prompted this ("I need to digitize a piece of music", "what is LOLA and
# how do I use it") and lets the short common ones go. Under-claiming is the
# side to err on: a replay left unattributed costs a slightly high count,
# and a patron called a script costs the count its meaning.
ECHO_MIN_CHARS = 20


def mark_bursts(rows: list) -> None:
    """Label runs of conversations opened too close together to be separate
    people. Mutates `rows` (each needs first_ts, questions, has_dev_row)."""
    ordered = sorted(
        [r for r in rows if r.get("first_ts")], key=lambda r: r["first_ts"])
    if len(ordered) < BURST_MIN:
        return

    run: list = [ordered[0]]
    runs: list = []
    for prev, cur in zip(ordered, ordered[1:]):
        if (cur["first_ts"] - prev["first_ts"]).total_seconds() <= BURST_GAP_S:
            run.append(cur)
        else:
            runs.append(run)
            run = [cur]
    runs.append(run)

    for group in runs:
        if len(group) < BURST_MIN:
            continue
        span = (group[-1]["first_ts"] - group[0]["first_ts"]).total_seconds()
        gaps = sorted(
            (b["first_ts"] - a["first_ts"]).total_seconds()
            for a, b in zip(group, group[1:]))
        median_gap = gaps[len(gaps) // 2] if gaps else None

        # Either signal is enough. The dev flag is a recorded fact; the
        # cadence is a physical impossibility. A run that has neither is
        # somebody working quickly, which is a different thing.
        by_flag = any(g.get("has_dev_row") for g in group)
        by_pace = median_gap is not None and median_gap <= SCRIPT_MEDIAN_GAP_S
        for g in group:
            g["burst"] = {
                "n": len(group),
                "span_s": span,
                "median_gap_s": median_gap,
                "scripted": by_flag or by_pace,
                "by_pace": by_pace and not by_flag,
            }


async def mark_replays(db: Any, rows: list) -> None:
    """Flag rows whose question was asked verbatim, earlier, by somebody else.

    One query for the whole page, keyed on the question text the page
    already holds.
    """
    candidates = {}
    for r in rows:
        for q in (r.get("questions") or []):
            if len(_repeat_key(q)) >= REPLAY_MIN_CHARS:
                candidates.setdefault(q, []).append(r)
    if not candidates:
        # Still worth the echo pass: it needs no distinctive question, only
        # that none of them was asked first.
        await _mark_echoes(db, rows)
        return
    try:
        earlier = await db.message.find_many(
            where={"type": "user", "content": {"in": list(candidates)}},
            order={"timestamp": "asc"}, take=2000)
    except Exception:  # noqa: BLE001
        return

    seen_first: dict = {}
    for m in earlier:
        content = getattr(m, "content", "")
        cid = getattr(m, "conversationId", None)
        ts = getattr(m, "timestamp", None)
        if content not in seen_first:
            seen_first[content] = (cid, ts)

    for text, targets in candidates.items():
        first_cid, first_ts = seen_first.get(text, (None, None))
        for r in targets:
            if first_cid and first_cid != r["conversation_id"]:
                r["is_replay"] = True

    await _mark_echoes(db, rows)


async def _mark_echoes(db: Any, rows: list) -> None:
    """Flag conversations in which nothing was asked first."""
    wanted: dict = {}
    for r in rows:
        if r.get("is_replay"):
            continue
        allq = [q for q in (r.get("questions") or []) if q]
        # At least one question substantial enough to be worth tracing, and
        # then EVERY question is checked -- a greeting does not excuse the
        # rest, and it does not condemn them either.
        if allq and any(len(_repeat_key(q)) >= ECHO_MIN_CHARS for q in allq):
            for q in allq:
                wanted.setdefault(q, []).append(r)
    if not wanted:
        return
    try:
        hits = await db.message.find_many(
            where={"type": "user", "content": {"in": list(wanted)}},
            order={"timestamp": "asc"}, take=3000)
    except Exception:  # noqa: BLE001
        return

    first_of: dict = {}
    for m in hits:
        c = getattr(m, "content", "")
        if c not in first_of:
            first_of[c] = getattr(m, "conversationId", None)

    originated: dict = {}
    for text, targets in wanted.items():
        for r in targets:
            cid = r["conversation_id"]
            originated.setdefault(cid, [False, r])
            if first_of.get(text) == cid:
                originated[cid][0] = True
    for cid, (did, r) in originated.items():
        if not did:
            r["is_echo"] = True


def _already_testing(conv: dict) -> bool:
    """True when something already attributes this conversation to testing."""
    if conv.get("origin") == "staff" or conv.get("has_dev_row"):
        return True
    burst = conv.get("burst")
    return bool(burst and burst.get("scripted"))


def _repeat_key(text: str) -> str:
    import re as _re
    return _re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def mark_repeats(rows: list) -> None:
    """Flag the same question asked again in a different conversation.

    ONLY among conversations nothing has attributed yet. The developer
    replayed 206 real patron questions through a script on 19-20 August, so
    every genuine question now has a scripted twin -- and counting those
    twins made the ORIGINAL look like somebody re-checking. One patron's
    question about SWORD was relabelled "possibly staff" by the replay of
    itself.

    Testing must not be allowed to reclassify the traffic it was testing.
    """
    seen: dict = {}
    rows = [r for r in rows if not _already_testing(r)]
    for r in rows:
        for q in (r.get("questions") or []):
            k = _repeat_key(q)
            if len(k) < 8:
                continue
            seen.setdefault(k, []).append(r)
    for k, group in seen.items():
        if len(group) < 2:
            continue
        for r in group:
            r["repeated_question"] = max(r.get("repeated_question", 0),
                                         len(group))

def _known_staff_addresses() -> frozenset:
    """Addresses that belong to people who run this service.

    Read from the settings that already list them -- the kill-switch
    operators and the SSO allow-list -- rather than a new list nobody would
    remember to update.
    """
    import os as _os
    out = set()
    for var in ("SERVICE_PAUSE_OPERATORS", "ALERT_EMAIL_TO",
                "ALERT_EMAIL_TO_URGENT"):
        for part in (_os.getenv(var, "") or "").replace(";", ",").split(","):
            part = part.strip().lower()
            if "@" in part:
                out.add(part)
    for uid in (_os.getenv("SSO_ALLOWED_UIDS", "") or "").replace(
            ";", ",").split(","):
        uid = uid.strip().lower()
        if uid:
            out.add(f"{uid}@miamioh.edu")
    return frozenset(out)


MANUAL_LABELS = {
    "local":  ("local test", "local"),
    "staff":  ("staff test", "staff"),
    "patron": ("patron", "patron-confirmed"),
}


def classify_source(conv: dict) -> dict:
    """{'label', 'why', 'tag'} for one conversation summary row.

    `conv` needs: questions, question_times, has_dev_row, origin.

    Order matters: recorded facts before readings. `origin` is the strongest
    signal there is -- somebody came through the staff link on purpose --
    and it outranks any amount of clever inference from the transcript.
    """
    # A person's verdict beats every rule here, including the recorded
    # ones. They can know things the data cannot hold -- that the colleague
    # at the next desk was the one testing, that a question came in by
    # phone and was typed in on somebody's behalf.
    manual = (conv.get("source_override") or "").strip().lower()
    if manual in MANUAL_LABELS:
        label, tag = MANUAL_LABELS[manual]
        who = conv.get("source_override_by") or "an operator"
        return {"label": label, "tag": tag, "manual": True,
                "why": f"Set by hand ({who}). A person's verdict overrides "
                       f"every rule on this page."}

    if conv.get("origin") == "staff":
        return {"label": "staff test", "tag": "staff",
                "why": "Arrived through the staff-test link — recorded at "
                       "connection, not inferred."}
    if conv.get("has_dev_row"):
        return {"label": "local test", "tag": "local",
                "why": "Reached the server with no browser origin — a script."}

    qs = conv.get("questions") or []
    joined = " ".join(qs).lower()

    note = (conv.get("feedback_comment") or "").strip().lower()
    if note:
        told = next((p for p in _FEEDBACK_TESTING if p in note), "")
        if told:
            return {"label": "staff test", "tag": "staff",
                    "why": f"The rating comment on this conversation says so "
                           f"(“{told}”) — a check or a demo, not a patron "
                           f"describing their own visit."}

    said = next((p for p in _SELF_DECLARED
                 if any(p in (q or "").lower()[:60] for q in qs)), "")
    if said:
        return {"label": "staff?", "tag": "maybe-staff",
                "why": f"They said so: “{said}” appears in the conversation."}

    hit = next((p for p in _THIRD_PARTY if p in joined), "")
    if hit:
        return {"label": "staff?", "tag": "maybe-staff",
                "why": f"Asks on somebody else's behalf (“{hit}”) — "
                       f"phrasing a patron does not use about themselves."}

    burst = conv.get("burst")
    if burst:
        if burst.get("by_pace"):
            return {"label": "local test", "tag": "local",
                    "why": f"One of {burst['n']} conversations opened a "
                           f"median {burst['median_gap_s']:.1f}s apart. "
                           f"Nobody reads an answer, opens a new window and "
                           f"types that fast — this is a script."}
        if burst["scripted"]:
            return {"label": "local test", "tag": "local",
                    "why": f"One of {burst['n']} conversations opened within "
                           f"{burst['span_s'] / 60:.0f} min, and one of them "
                           f"reached the server with no browser origin — the "
                           f"whole run was a script."}
        return {"label": "staff?", "tag": "maybe-staff",
                "why": f"One of {burst['n']} conversations opened within "
                       f"{burst['span_s'] / 60:.0f} min. A person opens one "
                       f"chat window; a run like this is somebody testing."}

    # AFTER the arrival signals above, not before. How a conversation
    # reached the server is a harder fact than what its text contains: a
    # script replaying a question that happens to hold a staff address is
    # still a script, and calling it staff testing would misattribute our
    # own replay to a colleague.
    from src.api.admin.staff_directory import looks_like_staff

    if looks_like_staff(joined) or any(
            a in joined.lower() for a in _known_staff_addresses()):
        return {"label": "staff test", "tag": "staff",
                "why": "A library staff address or NetID appears in this "
                       "conversation. Who is not recorded here."}

    if conv.get("is_echo"):
        return {"label": "local test", "tag": "local",
                "why": "Nothing in this conversation was asked first — every "
                       "question in it had already been put to the bot by "
                       "somebody else. A person originates at least one "
                       "question; a replay originates none."}

    if conv.get("is_replay"):
        return {"label": "local test", "tag": "local",
                "why": "This question was already asked, word for word, in an "
                       "earlier conversation. Forty characters of identical "
                       "text is a replay, not two people phrasing something "
                       "the same way."}

    if conv.get("repeated_question", 0) >= 2:
        return {"label": "staff?", "tag": "maybe-staff",
                "why": f"The same question appears in "
                       f"{conv['repeated_question']} separate conversations. "
                       f"A patron who got an answer does not re-ask it in a "
                       f"fresh window."}

    times = [t for t in (conv.get("question_times") or []) if t is not None]
    if len(qs) >= STAFF_MIN_QUESTIONS and len(times) >= 2:
        gaps = sorted((times[i + 1] - times[i]).total_seconds()
                      for i in range(len(times) - 1))
        median = gaps[len(gaps) // 2]
        if median <= STAFF_MAX_MEDIAN_GAP_S:
            return {"label": "staff?", "tag": "maybe-staff",
                    "why": f"{len(qs)} questions, median {median:.0f}s apart — "
                           f"the pace of working through a list, not of "
                           f"someone with a problem."}
    return {"label": "", "tag": "unlabelled", "why": ""}


async def sources_for_conversations(db: Any, conversation_ids: list) -> dict:
    """{conversation_id: source dict} for an arbitrary set of conversations.

    THE CONTEXT MATTERS, NOT JUST THE ROWS ASKED ABOUT. A scripted run is
    six conversations opened ninety seconds apart; if only one of them
    happens to be flagged and we classify that one alone, there is no run to
    see and it comes back unattributed. The first version did exactly that
    and swept nothing.

    So the window is widened to every conversation in the same span of time,
    which is also what the by-day view sees -- and the two must agree, or
    the queue and the conversation list would say different things about the
    same person.
    """
    ids = [c for c in set(conversation_ids or []) if c]
    if not ids:
        return {}

    # The span the asked-about conversations live in, padded so a run that
    # starts just before the first flagged row is still visible.
    try:
        anchors = await db.message.find_many(
            where={"conversationId": {"in": ids}}, order={"timestamp": "asc"})
    except Exception:  # noqa: BLE001
        return {}
    stamps = [getattr(x, "timestamp", None) for x in anchors]
    stamps = [t for t in stamps if t is not None]
    if not stamps:
        return {}
    pad = timedelta(minutes=10)

    # ONE WINDOW PER CLUSTER, NOT ONE WINDOW OVER EVERYTHING.
    #
    # This used to take min(stamps) to max(stamps) as a single span and read
    # it with take=5000. Ask about conversations from the 5th and the 25th
    # and that span is twenty days -- far more than 5000 messages -- and the
    # ascending sort meant the cap kept the OLDEST 5000 and silently dropped
    # everything recent. Measured 2026-08-25: 260 ids in, 39 of them came
    # back with no verdict at all, the examples all from the last few days.
    #
    # The direction of that loss is the dangerous one. No verdict means no
    # testing tag, and no testing tag reads as a member of the public, so
    # the wider the span asked about, the more our own scripted runs were
    # counted as patrons.
    #
    # Runs are bursts minutes apart with hours of nothing between them, so
    # the timeline is naturally clustered. Reading each cluster separately
    # costs a few small queries instead of one enormous one, and nothing in
    # between the clusters was ever needed.
    sorted_stamps = sorted(stamps)
    clusters: list = [[sorted_stamps[0], sorted_stamps[0]]]
    for t in sorted_stamps[1:]:
        if t - clusters[-1][1] > _CLUSTER_SPLIT:
            clusters.append([t, t])
        else:
            clusters[-1][1] = t

    msgs, seen_msg, truncated = [], set(), 0
    for c_lo, c_hi in clusters:
        try:
            batch = await db.message.find_many(
                where={"timestamp": {"gte": c_lo - pad, "lte": c_hi + pad}},
                order={"timestamp": "asc"}, take=_WINDOW_TAKE)
        except Exception:  # noqa: BLE001
            batch = []
        if len(batch) >= _WINDOW_TAKE:
            # Never a silent cap: a truncated cluster is a cluster whose
            # later conversations lost their run, which is exactly the bug
            # above in miniature.
            truncated += 1
        for x in batch:
            if x.id not in seen_msg:
                seen_msg.add(x.id)
                msgs.append(x)
    if truncated:
        logger.warning(
            "sources_for_conversations: %d of %d time windows hit the %d-row "
            "cap; conversations in those windows may be under-attributed",
            truncated, len(clusters), _WINDOW_TAKE)
    if not msgs:
        msgs = anchors

    missing = set(ids) - {getattr(x, "conversationId", None) for x in msgs}
    if missing:
        # Belt and braces: whatever the windows missed, classify on its own
        # rather than hand back nothing for it.
        msgs.extend(a for a in anchors
                    if getattr(a, "conversationId", None) in missing)

    window_ids = list({getattr(x, "conversationId", None) for x in msgs} - {None})
    try:
        usage = await db.modeltokenusage.find_many(
            where={"conversationId": {"in": window_ids}})
        dev = {u.conversationId for u in usage
               if "dev" in (getattr(u, "callSite", "") or "")}
    except Exception:  # noqa: BLE001
        dev = set()
    try:
        convs = await db.conversation.find_many(where={"id": {"in": window_ids}})
        origins = {c.id: getattr(c, "origin", None) for c in convs}
        overrides = {c.id: (getattr(c, "sourceOverride", None),
                            getattr(c, "sourceOverrideBy", None))
                     for c in convs}
    except Exception:  # noqa: BLE001
        origins, overrides = {}, {}
    # The rating comment, same as the by-day view reads. Without it this
    # function and list_conversations_on disagree about the same
    # conversation -- the dashboard called one "staff test" on the strength
    # of a comment reading "demo" while the daily mail counted it as patron
    # dissatisfaction.
    #
    # Its own try: a failure here must not also cost us the origins above,
    # which are the strongest evidence we hold.
    try:
        fbs = await db.conversationfeedback.find_many(
            where={"conversationId": {"in": window_ids}})
        notes = {f.conversationId: (getattr(f, "userComment", "") or "")
                 for f in fbs}
    except Exception:  # noqa: BLE001
        notes = {}

    slots: dict = {}
    for x in msgs:
        cid = getattr(x, "conversationId", None)
        if not cid:
            continue
        slot = slots.setdefault(cid, {
            "conversation_id": cid, "first_ts": getattr(x, "timestamp", None),
            "questions": [], "question_times": [],
        })
        if getattr(x, "type", "") == "user":
            slot["questions"].append(getattr(x, "content", "") or "")
            slot["question_times"].append(getattr(x, "timestamp", None))

    rows = list(slots.values())
    for v in rows:
        v["has_dev_row"] = v["conversation_id"] in dev
        v["origin"] = origins.get(v["conversation_id"])
        v["feedback_comment"] = notes.get(v["conversation_id"], "")
        ov, ov_by = overrides.get(v["conversation_id"], (None, None))
        v["source_override"] = ov
        v["source_override_by"] = ov_by
    mark_bursts(rows)
    mark_repeats(rows)
    return {v["conversation_id"]: classify_source(v) for v in rows}


TESTING_TAGS = frozenset({"local", "staff", "maybe-staff"})


async def close_testing_rows(db: Any, *, filter_preset: str = "flagged",
                             by: str = "operator",
                             dry_run: bool = True) -> dict:
    """Mark flagged turns that came from testing as reviewed.

    A flagged turn is a queue item that says "a patron may have had a bad
    experience here". A turn from our own scripted run says nothing of the
    kind, and 286 of the 300 sitting in the queue were exactly that -- the
    queue was mostly a record of us testing, which buries the fourteen that
    might be real.

    Testing rows only. A turn we cannot attribute stays in the queue: the
    cost of leaving one is that somebody reads it, and the cost of closing
    one wrongly is that nobody ever does.
    """
    try:
        rows = await db.message.find_many(
            where=flagged_where(filter_preset),
            order={"timestamp": "desc"}, take=2000)
    except Exception:  # noqa: BLE001
        return {"closed": 0, "kept": 0, "by_tag": {}, "dry_run": dry_run}

    sources = await sources_for_conversations(
        db, [getattr(r, "conversationId", None) for r in rows])

    from collections import Counter
    hits, kept = [], 0
    tally: Counter = Counter()
    for r in rows:
        tag = (sources.get(getattr(r, "conversationId", None)) or {}).get("tag")
        if tag in TESTING_TAGS:
            hits.append(r)
            tally[tag] += 1
        else:
            kept += 1

    if not dry_run:
        stamp = datetime.now(timezone.utc)
        for r in hits:
            try:
                await db.message.update(
                    where={"id": r.id},
                    data={"reviewedAt": stamp, "reviewedBy": by})
            except Exception:  # noqa: BLE001 -- one bad row must not stop the rest
                logger.warning("could not close flagged row %s", r.id,
                               exc_info=True)

    return {"closed": len(hits), "kept": kept, "by_tag": dict(tally),
            "dry_run": dry_run}


SEARCH_SCAN_CAP = 4000
"""How many matching messages to pull before grouping.

The table holds ~6,200 messages and grows by a few hundred a week, so a
`contains` scan is measured in milliseconds and a tsvector index would be
machinery for a problem nobody has. This cap exists so that stops being
true quietly rather than loudly: cross it and the page SAYS it truncated,
instead of showing a confident partial answer.
"""

SEARCH_MIN_LEN = 2


async def search_messages(
    db: Any,
    query: str,
    *,
    who: str = "any",
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Conversations containing `query`, newest first.

    WHY THIS EXISTS
        There was no keyword search anywhere in the console. Conversations
        are browsable one day at a time, Flagged filters by preset, tickets
        filter by status -- so "has anyone ever asked about Zotero" meant
        opening days one after another and reading. Every question about
        what patrons actually ask was gated behind that.

    `who` narrows to what the PATRON typed or what the BOT said. Both are
    real questions and they are not the same one: "did anyone ask about
    interlibrary loan" and "did we ever tell someone the wrong loan period"
    need different halves of the transcript.

    Returns one row per CONVERSATION, not per message, because ten hits in
    one chat is one thing to read, not ten. `hits` says how many matched
    inside it and `snippet` is the first match, so the row can be judged
    without opening it.
    """
    q = (query or "").strip()
    if len(q) < SEARCH_MIN_LEN:
        return {"rows": [], "total": 0, "offset": offset, "limit": limit,
                "truncated": False, "query": q}

    where: dict = {"content": {"contains": q, "mode": "insensitive"}}
    if who == "patron":
        where["type"] = "user"
    elif who == "bot":
        where["type"] = "assistant"

    try:
        msgs = await db.message.find_many(
            where=where,
            order={"timestamp": "desc"},
            take=SEARCH_SCAN_CAP,
        )
    except Exception:  # noqa: BLE001 -- a search must not 500 the console
        logger.exception("search_messages failed for %r", q)
        return {"rows": [], "total": 0, "offset": offset, "limit": limit,
                "truncated": False, "query": q, "error": True}

    truncated = len(msgs) >= SEARCH_SCAN_CAP
    if truncated:
        logger.warning("search hit the %d-message scan cap for %r",
                       SEARCH_SCAN_CAP, q)

    grouped: dict = {}
    for m in msgs:
        cid = getattr(m, "conversationId", None)
        if not cid:
            continue
        row = grouped.get(cid)
        if row is None:
            row = grouped[cid] = {
                "conversation_id": cid,
                "when": local_ts(getattr(m, "timestamp", None)),
                "_ts": getattr(m, "timestamp", None),
                "hits": 0,
                "snippet": "",
                "snippet_from": "",
            }
        row["hits"] += 1
        if not row["snippet"]:
            row["snippet"] = (getattr(m, "content", "") or "")[:300]
            row["snippet_from"] = (
                "patron" if getattr(m, "type", "") == "user" else "chatbot")

    rows = sorted(grouped.values(),
                  key=lambda r: (r["_ts"] is None, r["_ts"]), reverse=True)
    for r in rows:
        r.pop("_ts", None)
    total = len(rows)
    return {
        "rows": rows[offset:offset + limit],
        "total": total,
        "offset": offset,
        "limit": limit,
        "truncated": truncated,
        "query": q,
    }
