"""The ticket detail page: the transcript, the repeat count, the correction.

Written against the workflow, not the markup. The complaint that produced
this page was that finishing a report meant leaving it four times; these
assert that each of those trips is now unnecessary.
"""

import datetime as dt
from types import SimpleNamespace as NS

import pytest
from fastapi import Depends, FastAPI
from starlette.testclient import TestClient

from src.api.admin.ticket_router import (
    _pin_pattern,
    build_ticket_router,
)

TICKET = NS(
    id="t-1", createdAt=dt.datetime(2026, 8, 21, 14, tzinfo=dt.timezone.utc),
    librarianName="Kevin Messner", librarianEmail="messnekr@miamioh.edu",
    question="Where is the music library?",
    botAnswer="I don't have information about that.",
    expectedAnswer="Amos Music Library, 100 Center for Performing Arts.",
    sourceUrl="", status="open", reviewedAt=None, emailSent=True,
)


class _DB:
    def __init__(self, ticket=TICKET, msgs=None):
        self.created: list = []
        self._ticket = ticket
        self._msgs = msgs or []
        self.correctionticket = NS(find_unique=self._find_ticket,
                                   find_many=self._find_tickets,
                                   update=self._update)
        self.message = NS(find_many=self._find_msgs)
        self.manualcorrection = NS(create=self._create)
        self.conversation = NS(find_unique=self._find_conv)
        self.toolexecution = NS(find_many=self._none)
        # conversation_detail also reads these two; without them it raises,
        # returns None, and the transcript panel silently vanishes.
        self.modeltokenusage = NS(find_many=self._none)
        self.conversationfeedback = NS(find_unique=self._no_fb)

    async def _find_ticket(self, where=None): return self._ticket
    async def _find_tickets(self, **_): return [self._ticket] if self._ticket else []
    async def _update(self, **_): return self._ticket
    async def _none(self, **_): return []
    async def _no_fb(self, where=None): return None
    async def _find_conv(self, where=None):
        return NS(id="c-1", createdAt=TICKET.createdAt, toolUsed=[])

    async def _find_msgs(self, where=None, order=None, take=None):
        w = where or {}
        out = self._msgs
        if w.get("type"):
            out = [m for m in out if m.type == w["type"]]
        c = w.get("content")
        if isinstance(c, str):
            out = [m for m in out if (m.content or "") == c]
        elif isinstance(c, dict) and "contains" in c:
            out = [m for m in out
                   if c["contains"].lower() in (m.content or "").lower()]
        if w.get("conversationId"):
            out = [m for m in out if m.conversationId == w["conversationId"]]
        return out

    async def _create(self, data=None):
        self.created.append(data or {})
        return NS(id="mc-1", **(data or {}))


def _msg(cid, content, type_="user", **kw):
    return NS(id=f"{cid}:{content[:8]}:{type_}", conversationId=cid,
              content=content, type=type_,
              timestamp=dt.datetime(2026, 8, 20, 15, tzinfo=dt.timezone.utc),
              wasRefusal=kw.get("refusal", False), isPositiveRated=None,
              confidence="high", intent=None, citedUrls=[], citedChunkIds=[],
              modelUsed="", latencyMs=0, reviewedAt=None, reviewedBy=None,
              scopeCampus=None, scopeLibrary=None)


def client(db):
    async def _ok() -> None: return None
    app = FastAPI()
    app.include_router(build_ticket_router(
        {"db": db, "guard": _ok, "librarian_code": "x"}))
    return TestClient(app, raise_server_exceptions=False)


# --- the page loads, and is wired ------------------------------------------


def test_the_detail_page_opens():
    r = client(_DB()).get("/admin/tickets/t-1")
    assert r.status_code == 200
    assert "Where is the music library?" in r.text


def test_a_missing_ticket_404s_rather_than_500ing():
    r = client(_DB(ticket=None)).get("/admin/tickets/t-999")
    assert r.status_code == 404
    assert "not found" in r.text.lower()


def test_the_correction_post_is_wired_and_never_422s():
    """`request: Request` read as a body is a 422 on every submit.

    That exact defect shipped twice on 2026-08-21 in two other routers,
    because `from __future__ import annotations` leaves FastAPI resolving
    the name against module globals. This is the check the unit tests there
    did not have.
    """
    r = client(_DB()).post("/admin/tickets/t-1/correct",
                           data={"created_by": "qum@miamioh.edu",
                                 "replacement": "Amos Music Library.",
                                 "query_pattern": "(?i)music library"},
                           follow_redirects=False)
    assert r.status_code != 422, "the correction form is mis-wired"
    assert r.status_code == 303


# --- the correction, without leaving the page ------------------------------


def test_submitting_the_form_writes_a_pinned_correction():
    db = _DB()
    client(db).post("/admin/tickets/t-1/correct",
                    data={"created_by": "qum@miamioh.edu",
                          "replacement": "Amos Music Library.",
                          "query_pattern": "(?i)music library"},
                    follow_redirects=False)
    assert len(db.created) == 1
    c = db.created[0]
    assert c["action"] == "pin" and c["scope"] == "global"
    assert c["replacement"] == "Amos Music Library."
    assert c["createdBy"] == "qum@miamioh.edu"
    assert "t-1" in c["reason"], "the rule must name the ticket it came from"
    assert c["expiresAt"] is not None, "no correction outlives review"


def test_it_lands_back_on_the_ticket_not_somewhere_else():
    r = client(_DB()).post("/admin/tickets/t-1/correct",
                           data={"created_by": "a@miamioh.edu",
                                 "replacement": "x", "query_pattern": "y"},
                           follow_redirects=False)
    assert r.headers["location"].startswith("/admin/tickets/t-1")


@pytest.mark.parametrize("missing,why", [
    ({"replacement": "x", "query_pattern": "y"}, "email"),
    ({"created_by": "a@miamioh.edu", "query_pattern": "y"}, "answer"),
    ({"created_by": "a@miamioh.edu", "replacement": "x"}, "pattern"),
])
def test_an_incomplete_form_saves_nothing_and_says_why(missing, why):
    db = _DB()
    r = client(db).post("/admin/tickets/t-1/correct", data=missing,
                        follow_redirects=False)
    assert db.created == [], "a half-filled form must not create a rule"
    assert r.status_code == 303
    assert "msg=" in r.headers["location"]


def test_a_broken_regex_is_refused_before_it_reaches_the_database():
    # An invalid pattern stored as a live rule fails later, inside a turn,
    # where the operator will not connect it to this form.
    db = _DB()
    r = client(db).post("/admin/tickets/t-1/correct",
                        data={"created_by": "a@miamioh.edu",
                              "replacement": "x", "query_pattern": "([unclosed"},
                        follow_redirects=False)
    assert db.created == []
    assert "msg=" in r.headers["location"]


# --- the prefilled pattern -------------------------------------------------


def test_the_suggested_pattern_matches_the_question_it_came_from():
    import re
    q = "Where is the music library?"
    assert re.search(_pin_pattern(q), q)
    assert re.search(_pin_pattern(q), "WHERE IS THE MUSIC LIBRARY?")


def test_the_suggested_pattern_escapes_regex_characters():
    # "Do you have C++ books?" must not compile to a broken or greedy rule.
    import re
    q = "Do you have C++ books (any edition)?"
    pat = _pin_pattern(q)
    re.compile(pat)              # must not raise
    assert re.search(pat, q)


def test_an_empty_question_yields_no_pattern_rather_than_one_matching_all():
    assert _pin_pattern("") == ""
    assert _pin_pattern("   ") == ""


# --- the repeat count and the transcript -----------------------------------


def test_the_page_reports_how_often_the_same_thing_was_asked():
    db = _DB(msgs=[
        _msg("c-1", "Where is the music library?"),
        _msg("c-2", "where is the music library"),
        _msg("c-3", "when do you close"),
    ])
    text = client(db).get("/admin/tickets/t-1").text
    assert "Asked" in text
    assert "when do you close" not in text, "an unrelated question leaked in"


def test_it_says_so_plainly_when_nothing_matches():
    text = client(_DB(msgs=[])).get("/admin/tickets/t-1").text
    assert "No other conversation" in text


def test_the_transcript_is_shown_when_the_exact_question_is_found():
    db = _DB(msgs=[
        _msg("c-1", "Where is the music library?"),
        _msg("c-1", "I don't have information about that.", "assistant"),
    ])
    text = client(db).get("/admin/tickets/t-1").text
    assert "The conversation it came from" in text


def test_ticket_content_is_escaped():
    nasty = NS(**{**vars(TICKET), "question": "<script>alert(1)</script>"})
    text = client(_DB(ticket=nasty)).get("/admin/tickets/t-1").text
    assert "<script>alert(1)</script>" not in text
    assert "&lt;script&gt;" in text
