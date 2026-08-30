"""The librarian console, and the line between it and the operator one.

The failure that matters here is not a crash. It is the console showing a
subject librarian a list that is mostly us -- staff testing, replays, the
eval harness -- and teaching her in one visit that the bot gets ten
questions a day from her own colleagues.
"""

import datetime as dt

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.admin import librarian_router as LR
from src.api.admin import review_queries as RQ
from src.api.admin.sso import Caller, ROLE_LIBRARIAN, ROLE_OPERATOR

LIBRARIAN = Caller(role=ROLE_LIBRARIAN, uid="wardtd", via="sso")
OPERATOR = Caller(role=ROLE_OPERATOR, uid="qum", via="sso")


class _Msg:
    def __init__(self, cid, role, content, ts, mid="m1"):
        self.conversationId = cid
        self.type = role
        self.content = content
        self.timestamp = ts
        self.id = mid


class _DB:
    """Enough Prisma to answer the two queries these pages make."""

    def __init__(self, msgs):
        self._msgs = msgs
        outer = self

        class _Message:
            async def find_many(self, **kw):
                where = kw.get("where") or {}
                cid = where.get("conversationId")
                if cid:
                    return [m for m in outer._msgs if m.conversationId == cid]
                win = where.get("timestamp") or {}
                lo, hi = win.get("gte"), win.get("lt")
                return [m for m in outer._msgs
                        if (lo is None or m.timestamp >= lo)
                        and (hi is None or m.timestamp < hi)]

        class _Empty:
            async def find_many(self, **kw):
                return []

            async def find_unique(self, **kw):
                return None

        class _Conversation:
            async def find_unique(self, **kw):
                cid = (kw.get("where") or {}).get("id")
                if not any(m.conversationId == cid for m in outer._msgs):
                    return None

                class C:
                    createdAt = dt.datetime(2026, 8, 28, 14,
                                            tzinfo=dt.timezone.utc)
                    updatedAt = createdAt
                    toolUsed = None
                return C()

        self.message = _Message()
        self.conversation = _Conversation()
        self.modeltokenusage = _Empty()
        self.toolexecution = _Empty()
        self.conversationfeedback = _Empty()
        self.conversationsourceoverride = _Empty()


@pytest.fixture
def day():
    return dt.datetime(2026, 8, 28, 18, tzinfo=dt.timezone.utc)


def _client(db, caller=LIBRARIAN):
    async def _guard():
        return caller

    app = FastAPI()
    app.include_router(LR.build_librarian_router(
        {"db": db, "librarian_guard": _guard}))
    return TestClient(app)


# --- the scope -------------------------------------------------------------


@pytest.mark.asyncio
async def test_our_own_replays_are_not_shown_as_patron_questions(day):
    """The same question, word for word, in two conversations. The second
    is a replay -- the classifier calls it `bot`, and a librarian must not
    meet it as though a student had asked."""
    q = "what are the hours for king library on saturday morning"
    db = _DB([
        _Msg("c1", "user", q, day),
        _Msg("c2", "user", q, day + dt.timedelta(minutes=5)),
    ])
    scoped = await RQ.list_conversations_on(db, "2026-08-28",
                                            real_patrons_only=True)
    everything = await RQ.list_conversations_on(db, "2026-08-28")
    assert everything["total"] > scoped["total"], (
        "the operator console must still see both")


@pytest.mark.asyncio
async def test_a_conversation_a_person_confirmed_as_a_patron_is_shown(day):
    db = _DB([_Msg("c1", "user", "do you have a scanner on the third floor",
                   day)])
    got = await RQ.list_conversations_on(db, "2026-08-28",
                                         real_patrons_only=True)
    assert got["total"] == 1


@pytest.mark.asyncio
async def test_the_scope_is_applied_before_the_total(day):
    """A count computed before the filter produces a pager for rows the
    filter already threw away, which reads as a broken page."""
    q = "where is the writing center"
    db = _DB([
        _Msg("c1", "user", q, day),
        _Msg("c2", "user", q, day + dt.timedelta(minutes=2)),
        _Msg("c3", "user", "how do i renew a book", day),
    ])
    got = await RQ.list_conversations_on(db, "2026-08-28",
                                         real_patrons_only=True)
    assert got["total"] == len(got["rows"])


# --- the pages -------------------------------------------------------------


def test_the_list_says_what_it_is_leaving_out(day):
    """A filtered list that does not say it is filtered is a list somebody
    will quote a number out of."""
    db = _DB([_Msg("c1", "user", "is the library open on labor day", day)])
    body = _client(db).get("/librarian/conversations").text
    assert "testing" in body and "left out" in body


def test_the_librarian_console_has_no_operator_links(day):
    db = _DB([_Msg("c1", "user", "hi", day)])
    body = _client(db).get("/librarian/conversations").text
    for forbidden in ("/admin/cost", "/admin/service", "/admin/etl",
                      "/admin/audit", "/admin/corrections"):
        assert forbidden not in body, forbidden


def test_an_operator_may_read_the_librarian_console(day):
    """Operator is a superset. Anything else means checking a colleague's
    complaint requires signing out and back in as somebody else."""
    db = _DB([_Msg("c1", "user", "hi", day)])
    assert _client(db, OPERATOR).get(
        "/librarian/conversations").status_code == 200


def test_a_transcript_reads_as_the_patron_saw_it(day):
    db = _DB([
        _Msg("c1", "user", "where do i print", day, mid="m1"),
        _Msg("c1", "assistant", "King Library has printers on floor 1.",
             day + dt.timedelta(seconds=8), mid="m2"),
    ])
    body = _client(db).get("/librarian/conversations/c1").text
    assert "where do i print" in body
    assert "King Library has printers" in body
    assert "Patron" in body and "Chatbot" in body


def test_reporting_starts_from_the_turn_it_is_on(day):
    """Otherwise the form is a blank page asking her to describe what she
    is looking at."""
    db = _DB([
        _Msg("c1", "user", "who is the dean", day, mid="m1"),
        _Msg("c1", "assistant", "I could not find that.",
             day + dt.timedelta(seconds=5), mid="m2"),
    ])
    body = _client(db).get("/librarian/conversations/c1").text
    assert "conversation_id=c1" in body
    assert "message_id=m2" in body


def test_only_the_bot_s_turns_can_be_reported(day):
    """"This answer is wrong" on the patron's own question is nonsense."""
    db = _DB([
        _Msg("c1", "user", "who is the dean", day, mid="m1"),
        _Msg("c1", "assistant", "I could not find that.",
             day + dt.timedelta(seconds=5), mid="m2"),
    ])
    body = _client(db).get("/librarian/conversations/c1").text
    assert body.count("This answer is wrong") == 1
    assert "message_id=m1" not in body


def test_a_missing_conversation_says_so_rather_than_500(day):
    body = _client(_DB([])).get("/librarian/conversations/nope")
    assert body.status_code == 200
    assert "Not found" in body.text


def test_the_pages_are_not_indexable(day):
    db = _DB([_Msg("c1", "user", "hi", day)])
    c = _client(db)
    for path in ("/librarian/conversations", "/librarian/conversations/c1"):
        assert "noindex" in c.get(path).headers["x-robots-tag"], path


def test_it_opens_on_a_week_not_on_today(day):
    """A subject librarian does not open this every morning. Landing on an
    empty page because it is 9am is the version that gets bookmarked once
    and never opened again."""
    db = _DB([_Msg("c1", "user", "hi", day)])
    body = _client(db).get("/librarian/conversations").text
    assert "Last 7 days" in body
