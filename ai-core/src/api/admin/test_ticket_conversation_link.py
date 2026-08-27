"""A ticket points AT the conversation it came from, instead of describing it.

Until 2026-08-27 CorrectionTicket held only the librarian's typed copy of
the question and the answer, and the detail page reconstructed the link by
matching that typing against every question ever asked (>=0.99 overlap).
That finds nothing the moment they paraphrase, and finds the WRONG
conversation when two patrons type the same sentence. One ticket existed in
the table -- what a path nobody can walk looks like.

Both directions are tested: the ticket stores what it was given, and the
detail page prefers the stored id over the guess.
"""

import datetime as dt
from types import SimpleNamespace as NS

from fastapi import FastAPI
from starlette.testclient import TestClient

from src.api.admin.ticket_router import build_ticket_router

_WHEN = dt.datetime(2026, 8, 27, 14, tzinfo=dt.timezone.utc)


def _ticket(**kw):
    base = dict(
        id="t-1", createdAt=_WHEN, librarianName="Kevin Messner",
        librarianEmail="messnekr@miamioh.edu",
        question="Where is the music library?",
        botAnswer="I don't have information about that.",
        expectedAnswer="Amos Music Library.", sourceUrl="", status="open",
        reviewedAt=None, emailSent=True, conversationId=None, messageId=None,
    )
    base.update(kw)
    return NS(**base)


def _msg(cid, content, type_="user"):
    return NS(id=f"{cid}:{type_}", conversationId=cid, content=content,
              type=type_, timestamp=_WHEN, wasRefusal=False,
              isPositiveRated=None, confidence="high", intent=None,
              citedUrls=[], citedChunkIds=[], modelUsed="", latencyMs=0,
              reviewedAt=None, reviewedBy=None, scopeCampus=None,
              scopeLibrary=None)


class _DB:
    def __init__(self, ticket=None, msgs=None, conversations=("c-1",)):
        self.created: list = []
        self._ticket = ticket if ticket is not None else _ticket()
        self._msgs = msgs or []
        self._conversations = set(conversations)
        self.correctionticket = NS(find_unique=self._find_ticket,
                                   find_many=self._find_tickets,
                                   update=self._noop, create=self._create)
        self.message = NS(find_many=self._find_msgs)
        self.conversation = NS(find_unique=self._find_conv)
        self.toolexecution = NS(find_many=self._none)
        self.modeltokenusage = NS(find_many=self._none)
        self.conversationfeedback = NS(find_unique=self._no_fb)
        self.manualcorrection = NS(create=self._noop)

    async def _find_ticket(self, where=None): return self._ticket
    async def _find_tickets(self, **_): return []
    async def _noop(self, **kw): return NS(id="x", **(kw.get("data") or {}))
    async def _none(self, **_): return []
    async def _no_fb(self, where=None): return None

    async def _create(self, data=None):
        self.created.append(data or {})
        return NS(id="t-new")

    async def _find_conv(self, where=None):
        cid = (where or {}).get("id")
        if cid not in self._conversations:
            return None
        return NS(id=cid, createdAt=_WHEN, toolUsed=[])

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


def _client(db):
    async def _ok() -> None: return None
    app = FastAPI()
    app.include_router(build_ticket_router(
        {"db": db, "guard": _ok, "librarian_code": "x"}))
    return TestClient(app, raise_server_exceptions=False)


# --- filing: the ids are stored ------------------------------------------


def _submit(db, **extra):
    form = {
        "key": "x", "librarian_name": "Kevin", "librarian_email": "k@miamioh.edu",
        "question": "Where is the music library?",
        "bot_answer": "I don't know.", "expected_answer": "Amos Music Library.",
    }
    form.update(extra)
    return _client(db).post("/librarian/ticket", data=form)


def test_a_ticket_filed_from_a_conversation_records_it():
    db = _DB()
    r = _submit(db, conversation_id="c-42", message_id="m-7")
    assert r.status_code == 200
    assert db.created, "no ticket was written"
    assert db.created[0]["conversationId"] == "c-42"
    assert db.created[0]["messageId"] == "m-7"


def test_a_ticket_filed_from_the_bare_form_stores_no_link():
    """A librarian reporting what a patron told them at the desk has no
    conversation. Storing "" would make an unlinked ticket look linked."""
    db = _DB()
    _submit(db)
    assert db.created[0]["conversationId"] is None
    assert db.created[0]["messageId"] is None


def test_the_form_prefills_and_carries_the_ids():
    db = _DB()
    r = _client(db).get(
        "/librarian/ticket?key=x&conversation_id=c-42&message_id=m-7"
        "&question=Where+is+the+music+library%3F&bot_answer=I+don%27t+know."
    )
    assert r.status_code == 200
    assert 'name="conversation_id" value="c-42"' in r.text.replace("'", '"')
    assert 'name="message_id" value="m-7"' in r.text.replace("'", '"')
    assert "Where is the music library?" in r.text


def test_a_validation_error_does_not_lose_the_link():
    """The round-trip that would quietly downgrade a linked ticket to an
    unlinked one for anyone who mistyped a field."""
    db = _DB()
    r = _submit(db, conversation_id="c-42", message_id="m-7",
                librarian_email="not-an-email")
    assert r.status_code == 422
    assert 'name="conversation_id" value="c-42"' in r.text.replace("'", '"')


# --- reading: the stored id wins -----------------------------------------


def test_the_stored_id_is_used_even_when_the_wording_does_not_match():
    """The case the old guess could never handle: the librarian
    paraphrased, so nothing reaches 0.99 overlap."""
    db = _DB(
        ticket=_ticket(question="patron asked about the music library",
                       conversationId="c-1"),
        msgs=[_msg("c-1", "where do I find music scores"),
              _msg("c-1", "I don't have that.", "assistant")],
    )
    r = _client(db).get("/admin/tickets/t-1")
    assert r.status_code == 200
    assert "The conversation it came from" in r.text
    assert "recorded when the ticket was filed" in r.text
    assert "where do I find music scores" in r.text


def test_without_a_stored_id_the_wording_match_still_works():
    """Every ticket filed before this column existed, and anything
    reported from the desk. Losing the fallback would make the page worse
    for them, not better."""
    db = _DB(
        ticket=_ticket(conversationId=None),
        msgs=[_msg("c-1", "Where is the music library?"),
              _msg("c-1", "I don't have information about that.", "assistant")],
    )
    r = _client(db).get("/admin/tickets/t-1")
    assert r.status_code == 200
    assert "The conversation it came from" in r.text
    assert "matched by wording" in r.text


def test_a_link_to_a_conversation_we_no_longer_hold_says_so():
    """A vanished section reads as "there was no chat", which is a
    different and wrong fact."""
    db = _DB(ticket=_ticket(conversationId="c-gone"), conversations=())
    r = _client(db).get("/admin/tickets/t-1")
    assert r.status_code == 200
    assert "no longer held" in r.text
    assert "c-gone" in r.text
