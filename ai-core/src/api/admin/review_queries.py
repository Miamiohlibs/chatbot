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


async def list_conversations_on(db: Any, day: "str", *,
                                limit: int = 50,
                                offset: int = 0) -> dict:
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
        end_local = start_local + _td(days=1)
        start = start_local.astimezone(timezone.utc)
        end = end_local.astimezone(timezone.utc)
    except Exception:  # noqa: BLE001 -- a bad date must not 500 the page
        return {"rows": [], "total": 0, "offset": offset, "limit": limit}

    try:
        msgs = await db.message.find_many(
            where={"timestamp": {"gte": start, "lt": end}},
            order={"timestamp": "asc"},
        )
    except Exception:  # noqa: BLE001
        return {"rows": [], "total": 0, "offset": offset, "limit": limit}

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
    for v in out:
        v["has_dev_row"] = v["conversation_id"] in dev_ids

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
        r["source"] = classify_source(r)
    return {"rows": out, "total": total, "offset": offset, "limit": limit}


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

# Phrasing a patron does not use about themselves.
_THIRD_PARTY = (
    "i have a student", "a student who", "professor wanting",
    "patron asked", "someone asked", "hi librarians",
    "a faculty member", "one of our students",
)


def classify_source(conv: dict) -> dict:
    """{'label': str, 'why': str} for one conversation summary row.

    `conv` needs: questions (list[str]), question_times (list[datetime]),
    has_dev_row (bool).
    """
    if conv.get("has_dev_row"):
        return {"label": "local test",
                "why": "Reached the server with no browser origin — a script."}

    qs = conv.get("questions") or []
    joined = " ".join(qs).lower()
    hit = next((p for p in _THIRD_PARTY if p in joined), "")
    if hit:
        return {"label": "staff?",
                "why": f"Asks on somebody else's behalf (“{hit}”) — "
                       f"phrasing a patron does not use about themselves."}

    times = [t for t in (conv.get("question_times") or []) if t is not None]
    if len(qs) >= STAFF_MIN_QUESTIONS and len(times) >= 2:
        gaps = sorted((times[i + 1] - times[i]).total_seconds()
                      for i in range(len(times) - 1))
        median = gaps[len(gaps) // 2]
        if median <= STAFF_MAX_MEDIAN_GAP_S:
            return {"label": "staff?",
                    "why": f"{len(qs)} questions, median {median:.0f}s apart — "
                           f"the pace of working through a list, not of "
                           f"someone with a problem."}
    return {"label": "", "why": ""}
