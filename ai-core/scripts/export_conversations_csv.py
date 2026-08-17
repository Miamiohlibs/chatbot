"""Export conversations to CSV for colleague review.

    .venv/bin/python -m scripts.export_conversations_csv \
        --from 2026-08-13 --to 2026-08-17

Writes to /opt/chatbot-private-data/exports/ -- NOT into the repo, because
every row contains real patron questions.

ONE ROW PER TURN
    The question and the answer sit on the same row. A row-per-message export
    splits them and is unreadable for the people who need to read it.

WHAT "SAME VISITOR" CAN AND CANNOT MEAN HERE
    The operator asked to flag conversations that are probably one person.
    Be exact about what is possible: NOTHING in the database identifies a
    visitor. Conversation holds an id and two timestamps. The rate limiter
    knows the client address but keeps it in memory and never writes it down,
    and nginx's access log has addresses but no conversation ids, so the two
    cannot be joined after the fact.

    So `burst_id` groups conversations that START within --gap minutes of the
    previous one's LAST activity. That is a TIME heuristic. Two people asking
    at 2pm land in one burst; one person returning after an hour lands in
    two. The column names say `possible_`, and the header row of the file
    repeats the caveat, so nobody reads a guess as a fact.

    `burst_pattern` is the more useful signal, because the two shapes look
    nothing alike:

      automated_like        many conversations, ~2 messages each, gaps under
                            a second -- a script. Our own probe runs look
                            exactly like this.
      sustained_single      few conversations, many messages, 30-90s apart --
                            a person typing and reading.
      normal                everything else.

    Measured while building this: 08-13 06-07h EDT had 306 conversations of
    ~2 messages (pre-launch, our own test scripts), while 08-17 17:30 had ONE
    conversation with 72 messages over 39 minutes. Both are "a lot of
    traffic"; only the second is a person.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ENV = Path("/opt/chatbot/.env")
if _ENV.exists():  # same loader the other scripts use
    for _line in _ENV.read_text().splitlines():
        if _line.strip() and not _line.strip().startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

EXPORT_DIR = Path(os.getenv("CONVERSATION_EXPORT_DIR",
                            "/opt/chatbot-private-data/exports"))
TZ = "America/New_York"

COLUMNS = [
    # grouping / traffic shape
    "possible_visitor_burst", "burst_pattern", "burst_conversations",
    "burst_messages", "burst_span_min", "gap_before_conv_min",
    # conversation
    "conversation_id", "conv_started_et", "conv_messages", "conv_span_min",
    "conv_messages_per_min",
    # the turn
    "turn", "asked_et", "user_question", "bot_answer", "reply_seconds",
    # system tags
    "intent", "scope_campus", "scope_library", "scope_source",
    "model_used", "confidence", "was_refusal", "refusal_trigger",
    "short_circuit_or_agent",
    # patron feedback
    "thumbs", "conv_star_rating", "conv_comment",
    # provenance
    "cited_urls", "cited_chunk_ids", "tools_called",
    # cost
    "prompt_tokens", "cached_tokens", "completion_tokens", "total_tokens",
    # triage
    "reviewed_at",
]


def _fmt(dt_: "datetime | None") -> str:
    if dt_ is None:
        return ""
    from zoneinfo import ZoneInfo

    aware = dt_ if dt_.tzinfo else dt_.replace(tzinfo=timezone.utc)
    return aware.astimezone(ZoneInfo(TZ)).strftime("%Y-%m-%d %H:%M:%S")


def _mins(a, b) -> str:
    if a is None or b is None:
        return ""
    return f"{(b - a).total_seconds() / 60.0:.1f}"


def _classify(convs: list) -> str:
    """automated_like / sustained_single / normal -- see the module docstring."""
    n_conv = len(convs)
    msgs = sum(len(c["messages"]) for c in convs)
    if n_conv >= 20 and msgs / max(n_conv, 1) <= 3:
        return "automated_like"
    for c in convs:
        if len(c["messages"]) >= 20:
            return "sustained_single"
    return "normal"


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from", dest="date_from", required=True)
    ap.add_argument("--to", dest="date_to", required=True,
                    help="INCLUSIVE end date")
    ap.add_argument("--gap", type=int, default=30,
                    help="minutes of silence that starts a new burst (30)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    # The dates are LIBRARY-LOCAL dates, because every timestamp in the file
    # is library-local and a range that did not match would be a trap. Naive
    # UTC bounds put the first row at 08-12 22:49 ET for a range asked for as
    # "13th to 17th" -- caught on the first run.
    from zoneinfo import ZoneInfo

    _tz = ZoneInfo(TZ)
    start = datetime.fromisoformat(args.date_from).replace(tzinfo=_tz)
    end = (datetime.fromisoformat(args.date_to).replace(tzinfo=_tz)
           + timedelta(days=1))

    from prisma import Prisma

    db = Prisma()
    await db.connect()
    try:
        convs_raw = await db.conversation.find_many(
            where={"createdAt": {"gte": start, "lt": end}},
            order={"createdAt": "asc"},
        )
        conv_ids = [c.id for c in convs_raw]
        if not conv_ids:
            print("no conversations in that range")
            return 1

        msgs = await db.message.find_many(
            where={"conversationId": {"in": conv_ids}},
            order={"timestamp": "asc"},
        )
        toks = await db.modeltokenusage.find_many(
            where={"conversationId": {"in": conv_ids}})
        tools = await db.toolexecution.find_many(
            where={"conversationId": {"in": conv_ids}})
        fbs = await db.conversationfeedback.find_many(
            where={"conversationId": {"in": conv_ids}})
    finally:
        await db.disconnect()

    by_conv: dict = {c.id: {"conv": c, "messages": []} for c in convs_raw}
    for m in msgs:
        if m.conversationId in by_conv:
            by_conv[m.conversationId]["messages"].append(m)
    fb_by_conv = {f.conversationId: f for f in fbs}
    tools_by_conv: dict = {}
    for t in tools:
        tools_by_conv.setdefault(t.conversationId, []).append(t.toolName)
    # Token rows have no message id, so they are summed per conversation and
    # attributed to the conversation, not the turn. Stated in the header note
    # rather than silently spread across turns.
    tok_by_conv: dict = {}
    for t in toks:
        d = tok_by_conv.setdefault(t.conversationId,
                                   {"p": 0, "c": 0, "o": 0, "t": 0})
        d["p"] += int(t.promptTokens or 0)
        d["c"] += int(t.cachedInputTokens or 0)
        d["o"] += int(t.completionTokens or 0)
        d["t"] += int(t.totalTokens or 0)

    # --- burst grouping -------------------------------------------------
    ordered = [by_conv[c.id] for c in convs_raw]
    bursts: list = []
    current: list = []
    prev_end = None
    gaps: dict = {}
    for item in ordered:
        c = item["conv"]
        ms = item["messages"]
        last = ms[-1].timestamp if ms else c.createdAt
        gap_min = None
        if prev_end is not None:
            gap_min = (c.createdAt - prev_end).total_seconds() / 60.0
        gaps[c.id] = gap_min
        if prev_end is None or (gap_min is not None and gap_min <= args.gap):
            current.append(item)
        else:
            bursts.append(current)
            current = [item]
        prev_end = last
    if current:
        bursts.append(current)

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(EXPORT_DIR, 0o700)
    out = Path(args.out) if args.out else (
        EXPORT_DIR / f"conversations-{args.date_from}-to-{args.date_to}.csv")

    rows_written = 0
    with out.open("w", newline="", encoding="utf-8") as fh:
        fh.write(
            "# Miami University Libraries Smart Chatbot -- conversation export\n"
            f"# range {args.date_from}..{args.date_to} inclusive, "
            f"times are {TZ} (ET)\n"
            "# CONTAINS REAL PATRON QUESTIONS -- handle as patron records.\n"
            "# possible_visitor_burst is a TIME heuristic, NOT an identity: "
            "nothing in the database identifies a visitor.\n"
            "# Conversations starting within "
            f"{args.gap} min of the previous one's last message share a burst. "
            "Two people at once look like one; one person returning later "
            "looks like two.\n"
            "# burst_pattern: automated_like = many conversations of ~2 "
            "messages (a script, incl. our own pre-launch test runs); "
            "sustained_single = one conversation with many messages minutes "
            "apart (a person); normal = neither.\n"
            "# token counts are per CONVERSATION (the token table has no "
            "message id), repeated on each of that conversation's rows.\n"
        )
        w = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()

        for bi, burst in enumerate(bursts, 1):
            b_msgs = sum(len(x["messages"]) for x in burst)
            b_all = [m for x in burst for m in x["messages"]]
            b_span = _mins(min((m.timestamp for m in b_all), default=None),
                           max((m.timestamp for m in b_all), default=None))
            pattern = _classify(burst)
            for item in burst:
                c = item["conv"]
                ms = item["messages"]
                c_span = _mins(min((m.timestamp for m in ms), default=None),
                               max((m.timestamp for m in ms), default=None))
                per_min = ""
                if ms and c_span not in ("", "0.0"):
                    per_min = f"{len(ms) / float(c_span):.1f}"
                fb = fb_by_conv.get(c.id)
                tk = tok_by_conv.get(c.id, {})
                base = {
                    "possible_visitor_burst": f"B{bi:04d}",
                    "burst_pattern": pattern,
                    "burst_conversations": len(burst),
                    "burst_messages": b_msgs,
                    "burst_span_min": b_span,
                    "gap_before_conv_min": (
                        "" if gaps.get(c.id) is None
                        else f"{gaps[c.id]:.1f}"),
                    "conversation_id": c.id,
                    "conv_started_et": _fmt(c.createdAt),
                    "conv_messages": len(ms),
                    "conv_span_min": c_span,
                    "conv_messages_per_min": per_min,
                    "conv_star_rating": "" if not fb else fb.rating,
                    "conv_comment": "" if not fb else (fb.userComment or ""),
                    "tools_called": "|".join(tools_by_conv.get(c.id, [])),
                    "prompt_tokens": tk.get("p", ""),
                    "cached_tokens": tk.get("c", ""),
                    "completion_tokens": tk.get("o", ""),
                    "total_tokens": tk.get("t", ""),
                }
                # Pair each assistant message with the user message before it.
                turn = 0
                pending_q = None
                pending_q_at = None
                for m in ms:
                    if (m.type or "").lower() == "user":
                        pending_q = m.content or ""
                        pending_q_at = m.timestamp
                        continue
                    turn += 1
                    thumbs = ("up" if m.isPositiveRated is True
                              else "down" if m.isPositiveRated is False else "")
                    row = dict(base)
                    row.update({
                        "turn": turn,
                        "asked_et": _fmt(pending_q_at or m.timestamp),
                        "user_question": pending_q or "",
                        "bot_answer": m.content or "",
                        "reply_seconds": (
                            "" if pending_q_at is None
                            else f"{(m.timestamp - pending_q_at).total_seconds():.1f}"),
                        "intent": m.intent or "",
                        "scope_campus": m.scopeCampus or "",
                        "scope_library": m.scopeLibrary or "",
                        "scope_source": m.scopeSource or "",
                        "model_used": m.modelUsed or "",
                        "confidence": m.confidence or "",
                        "was_refusal": "yes" if m.wasRefusal else "",
                        "refusal_trigger": m.refusalTrigger or "",
                        # A turn with no token rows and no tools was answered
                        # by a deterministic short-circuit -- useful for
                        # telling "the bot decided" from "we hard-coded it".
                        "short_circuit_or_agent": (
                            "short_circuit" if not tk.get("t") else "agent"),
                        "thumbs": thumbs,
                        "cited_urls": "|".join(
                            list(getattr(m, "citedUrls", None) or [])),
                        "cited_chunk_ids": "|".join(
                            list(getattr(m, "citedChunkIds", None) or [])),
                        "reviewed_at": _fmt(getattr(m, "reviewedAt", None)),
                    })
                    w.writerow(row)
                    rows_written += 1
                    pending_q, pending_q_at = None, None
                if turn == 0:
                    w.writerow(dict(base, turn=0, asked_et=_fmt(c.createdAt)))
                    rows_written += 1

    os.chmod(out, 0o600)
    print(f"  wrote {out}")
    print(f"  {rows_written} rows, {len(convs_raw)} conversations, "
          f"{len(bursts)} bursts")
    counts: dict = {}
    for b in bursts:
        counts[_classify(b)] = counts.get(_classify(b), 0) + 1
    print(f"  burst patterns: {counts}")
    heavy = sorted(
        ((len(x["messages"]), x["conv"].id) for b in bursts for x in b),
        reverse=True)[:5]
    print("  heaviest single conversations (messages, id):")
    for n, cid in heavy:
        print(f"    {n:4d}  {cid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
