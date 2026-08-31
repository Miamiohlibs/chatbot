"""
Offline tests for the Op-1 read-only review surface.

Run: `python -m src.api.admin.test_review` from ai-core/.

No real DB / no API: a stub Prisma-shaped object feeds canned rows.
Covers the load-bearing logic (filter selection, defensive empties,
handoff/outcome extraction) AND the security gate (fail-closed auth +
that the surface 401s without the token), via Starlette TestClient.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_HERE = Path(__file__).resolve().parent
_AI_CORE = _HERE.parent.parent.parent
sys.path.insert(0, str(_AI_CORE))

from src.api.admin.review_queries import conversation_detail, list_flagged
from src.api.admin.review_view_router import (
    build_review_view_router,
    make_token_guard,
)
from src.api.admin.reviews_router import build_reviews_router


def _msg(**kw):
    base = dict(id="m1", type="assistant", content="hi", timestamp="t",
                conversationId="c1", isPositiveRated=None, intent="hours",
                scopeCampus="oxford", scopeLibrary=None, modelUsed="x",
                confidence=None, wasRefusal=False, refusalTrigger=None,
                citedChunkIds=[])
    base.update(kw)
    return SimpleNamespace(**base)


class _StubDB:
    """Records the `where` list_flagged builds; returns canned rows."""

    def __init__(self, msgs=None, conv=None, toks=None, tools=None, fb=None,
                 fb_many=None):
        self._fb_many = fb_many or []
        self._msgs = msgs or []
        self._conv = conv
        self._toks = toks or []
        self._tools = tools or []
        self._fb = fb
        self.last_where = None

        async def _find_many(**kw):
            self.last_where = kw.get("where")
            return self._msgs

        async def _find_unique(**kw):
            return self._conv

        self.message = SimpleNamespace(
            find_many=_find_many,
            count=lambda: _aw(len(self._msgs)),
        )
        self.conversation = SimpleNamespace(find_unique=_find_unique)
        self.modeltokenusage = SimpleNamespace(
            find_many=lambda **k: _aw(self._toks))
        self.toolexecution = SimpleNamespace(
            find_many=lambda **k: _aw(self._tools))
        self.updated: dict = {}

        async def _update(**kw):
            self.updated = kw
            return SimpleNamespace(id=kw.get("where", {}).get("id"))

        self.message.update = _update
        self.conversationfeedback = SimpleNamespace(
            find_unique=lambda **k: _aw(self._fb),
            # list view batches ratings across the page
            find_many=lambda **k: _aw(self._fb_many))


def _aw(v):
    async def _c():
        return v
    return _c()


def _run(coro):
    return asyncio.run(coro)


# --- query logic ---------------------------------------------------------

def test_list_flagged_filter_presets_build_right_where() -> None:
    """Working views are scoped to UNREVIEWED rows (2026-07-27): the
    queue has to shrink as the operator triages, or fresh and
    already-handled rows are indistinguishable."""
    db = _StubDB(msgs=[_msg(isPositiveRated=False)])
    _run(list_flagged(db, filter_preset="thumbs_down"))
    assert db.last_where == {
        "AND": [{"isPositiveRated": False}, {"reviewedAt": None}]
    }, db.last_where
    _run(list_flagged(db, filter_preset="thumbs_up"))
    assert db.last_where == {
        "AND": [{"isPositiveRated": True}, {"reviewedAt": None}]
    }, db.last_where
    _run(list_flagged(db, filter_preset="refusal"))
    assert db.last_where == {
        "AND": [{"wasRefusal": True}, {"reviewedAt": None}]
    }
    _run(list_flagged(db, filter_preset="bogus"))  # -> flagged union
    assert "OR" in db.last_where["AND"][0]
    # The two escape hatches keep showing handled rows.
    _run(list_flagged(db, filter_preset="all"))
    assert db.last_where == {}
    _run(list_flagged(db, filter_preset="reviewed"))
    assert db.last_where == {"NOT": [{"reviewedAt": None}]}


def test_attach_feedback_annotates_rows_by_conversation() -> None:
    """Star ratings live on the conversation; the queue lists messages.
    One batched lookup projects them onto the rows so a reviewer can
    see WHICH rows have patron feedback without opening each."""
    from src.api.admin.review_queries import attach_feedback

    class _FBDB:
        conversationfeedback = SimpleNamespace(
            find_many=lambda **k: _aw([
                SimpleNamespace(conversationId="c1", rating=4,
                                userComment="helpful"),
            ])
        )

    rows = [{"conversation_id": "c1"}, {"conversation_id": "c2"}]
    out = _run(attach_feedback(_FBDB(), rows))
    assert out[0]["feedback_rating"] == 4
    assert out[0]["feedback_comment"] == "helpful"
    assert out[1]["feedback_rating"] is None


def test_attach_feedback_never_raises() -> None:
    from src.api.admin.review_queries import attach_feedback

    class _Boom:
        conversationfeedback = SimpleNamespace(
            find_many=lambda **k: (_ for _ in ()).throw(RuntimeError("x")))

    rows = [{"conversation_id": "c1"}]
    assert _run(attach_feedback(_Boom(), rows)) == rows


def test_mark_reviewed_sets_and_clears() -> None:
    from src.api.admin.review_queries import mark_reviewed

    seen: dict = {}

    class _UpDB:
        message = SimpleNamespace(
            update=lambda **k: (seen.update(k), _aw(True))[1])

    assert _run(mark_reviewed(_UpDB(), "m1", reviewed_by="qum")) is True
    assert seen["data"]["reviewedBy"] == "qum"
    assert seen["data"]["reviewedAt"] is not None
    assert _run(mark_reviewed(_UpDB(), "m1", undo=True)) is True
    assert seen["data"] == {"reviewedAt": None, "reviewedBy": None}


def test_mark_reviewed_never_raises() -> None:
    from src.api.admin.review_queries import mark_reviewed

    class _Boom:
        message = SimpleNamespace(
            update=lambda **k: (_ for _ in ()).throw(RuntimeError("x")))

    assert _run(mark_reviewed(_Boom(), "m1")) is False


def test_list_flagged_defensive_on_query_error() -> None:
    class _Boom:
        message = SimpleNamespace(
            find_many=lambda **k: (_ for _ in ()).throw(RuntimeError("x")))
    out = _run(list_flagged(_Boom(), filter_preset="all"))
    assert out == []  # never raises into the endpoint


def test_conversation_detail_extracts_handoff_and_outcome() -> None:
    msgs = [
        _msg(id="u", type="user", content="q", wasRefusal=False),
        _msg(id="a", type="assistant", content="final",
             wasRefusal=True, refusalTrigger="human_handoff",
             confidence="low"),
    ]
    db = _StubDB(
        msgs=msgs,
        conv=SimpleNamespace(createdAt="c", updatedAt="u", toolUsed=[]),
        toks=[SimpleNamespace(llmModelName="gpt-5.4-nano", callSite="judge",
                              promptTokens=10, cachedInputTokens=2,
                              completionTokens=3, totalTokens=13,
                              createdAt="t")],
        tools=[SimpleNamespace(agentName="A", toolName="search_kb",
                               success=True, executionTime=5,
                               timestamp="t")],
        fb=SimpleNamespace(rating=1, userComment="bad"),
    )
    d = _run(conversation_detail(db, "c1"))
    assert d is not None
    assert d["token_total"] == 13
    assert len(d["tools_called"]) == 1
    assert d["human_handoff"] and d["human_handoff"][0]["trigger"] == "human_handoff"
    assert d["outcome"]["final_answer"] == "final"
    assert d["outcome"]["was_refusal"] is True
    assert d["feedback"]["rating"] == 1


def test_conversation_detail_none_when_missing() -> None:
    assert _run(conversation_detail(_StubDB(conv=None), "nope")) is None
    assert _run(conversation_detail(_StubDB(), "")) is None


# --- security gate (fail-closed) -----------------------------------------

def _client(token: str):
    from fastapi import FastAPI
    from starlette.testclient import TestClient

    db = _StubDB(
        msgs=[_msg(isPositiveRated=False, conversationId="c1")],
        conv=SimpleNamespace(createdAt="c", updatedAt="u", toolUsed=[]),
    )
    guard = make_token_guard(token)
    deps = {"db": db, "require_librarian": guard, "guard": guard}
    app = FastAPI()
    app.include_router(build_reviews_router(deps))
    app.include_router(build_review_view_router(deps))
    return TestClient(app, raise_server_exceptions=False)


def test_html_and_json_401_without_token() -> None:
    c = _client("s3cret")
    assert c.get("/admin/review").status_code == 401
    assert c.get("/admin/reviews").status_code == 401
    assert c.get("/admin/review?key=wrong").status_code == 401


def test_html_and_json_ok_with_token() -> None:
    c = _client("s3cret")
    # The HTML list moved to /admin/conversations (2026-08-27); this URL
    # still answers, as a redirect, because it is in bookmarks. Not
    # followed here: the conversations router is not mounted on this test
    # app, so following would 404 on a route that exists in production.
    r = c.get("/admin/review?key=s3cret", follow_redirects=False)
    assert r.status_code == 307
    # The JSON API is unchanged -- it has consumers that are not a browser.
    rj = c.get("/admin/reviews", headers={"X-Admin-Token": "s3cret"})
    assert rj.status_code == 200 and "results" in rj.json()


def test_empty_token_is_fail_closed() -> None:
    c = _client("")  # misconfig -> everything 401, never open
    assert c.get("/admin/review?key=").status_code == 401
    assert c.get("/admin/reviews", headers={"X-Admin-Token": ""}).status_code == 401


def test_html_escapes_user_content() -> None:
    """Conversation content is attacker-controlled; it must be escaped
    in the librarian's browser (stored-XSS guard)."""
    from fastapi import FastAPI
    from starlette.testclient import TestClient

    xss = "<script>alert(1)</script>"
    db = _StubDB(
        msgs=[_msg(id="x", type="user", content=xss, conversationId="c1")],
        conv=SimpleNamespace(createdAt="c", updatedAt="u", toolUsed=[]),
    )
    g = make_token_guard("k")
    app = FastAPI()
    app.include_router(build_review_view_router(
        {"db": db, "guard": g, "require_librarian": g}))
    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/admin/review/c1?key=k")
    assert r.status_code == 200
    assert "<script>alert(1)</script>" not in r.text
    assert "&lt;script&gt;" in r.text


def test_conversation_page_shows_the_passages_and_links_to_the_fix() -> None:
    """`suppress` and `replace` corrections are keyed by chunk id, and
    until 2026-08-08 no operator surface displayed a chunk id -- so two
    of the four correction types were unfileable from the console."""
    from fastapi import FastAPI
    from starlette.testclient import TestClient

    db = _StubDB(
        msgs=[_msg(id="a1", type="assistant", content="the answer",
                   conversationId="c1", citedChunkIds=["chunk-77"])],
        conv=SimpleNamespace(createdAt="c", updatedAt="u", toolUsed=[]),
    )
    g = make_token_guard("k")
    app = FastAPI()
    app.include_router(build_review_view_router(
        {"db": db, "guard": g, "require_librarian": g}))
    r = TestClient(app).get("/admin/review/c1?key=k")

    assert r.status_code == 200
    assert "chunk-77" in r.text, "the id has to be visible to be usable"
    assert "action=suppress&target=chunk-77" in r.text
    assert "action=replace&target=chunk-77" in r.text
    assert "key=k" in r.text, "the handoff must carry the operator's key"


def test_conversation_page_omits_the_passage_block_when_there_are_none() -> None:
    from fastapi import FastAPI
    from starlette.testclient import TestClient

    db = _StubDB(
        msgs=[_msg(id="a1", type="assistant", content="hi",
                   conversationId="c1", citedChunkIds=[])],
        conv=SimpleNamespace(createdAt="c", updatedAt="u", toolUsed=[]),
    )
    g = make_token_guard("k")
    app = FastAPI()
    app.include_router(build_review_view_router(
        {"db": db, "guard": g, "require_librarian": g}))
    r = TestClient(app).get("/admin/review/c1?key=k")
    assert "Passages this answer came from" not in r.text


def main() -> int:
    tests = [
        test_list_flagged_filter_presets_build_right_where,
        test_list_flagged_defensive_on_query_error,
        test_conversation_detail_extracts_handoff_and_outcome,
        test_conversation_detail_none_when_missing,
        test_html_and_json_401_without_token,
        test_html_and_json_ok_with_token,
        test_empty_token_is_fail_closed,
        test_html_escapes_user_content,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())


def test_the_flagged_list_now_redirects_to_conversations() -> None:
    """Flagged listed MESSAGES by preset and dropped them once marked
    handled. The conversations view could do neither -- until it grew a
    date range, an "only what went wrong" filter, the same flag presets,
    the patron's rating and the classified intent inline.

    What is left of the difference is the mark-handled queue, and NOBODY
    EVER USED IT: reviewedAt is null on all 3,096 assistant messages ever
    logged, which is why 318 rows sat in a queue that never shrank.

    A redirect, not a deletion: this URL is in browser history and in
    bookmarks, and a 404 reads as the console being broken. The
    capabilities themselves are asserted on the conversations page --
    see test_conversation_range.py and test_merged_view.py.
    """
    from fastapi import FastAPI
    from starlette.testclient import TestClient

    db = _StubDB(msgs=[_msg(id="m9", isPositiveRated=True, conversationId="c1")])
    guard = make_token_guard("s3cret")
    app = FastAPI()
    app.include_router(build_review_view_router(
        {"db": db, "guard": guard, "require_librarian": guard}))
    c = TestClient(app, raise_server_exceptions=False, follow_redirects=False)

    r = c.get("/admin/review?filter=thumbs_up&key=s3cret")
    assert r.status_code == 307
    assert "/admin/conversations" in r.headers["location"]
    assert "flag=thumbs_up" in r.headers["location"]

    # The default preset is the union of the three bad signals, which is
    # what needs=1 means on the other page.
    r2 = c.get("/admin/review?key=s3cret")
    assert "needs=1" in r2.headers["location"]

    # And it must span the beta, not land on today alone -- a preset that
    # covered all time becoming a single day would read as "nothing here".
    assert "day=2026-08-13" in r2.headers["location"]
    assert "to=" in r2.headers["location"]


def test_the_transcript_page_is_not_redirected() -> None:
    """/admin/review/{id} is the transcript, and tickets, search and every
    list row link into it. Only the LIST moved."""
    from fastapi import FastAPI
    from starlette.testclient import TestClient

    db = _StubDB(msgs=[_msg(id="m1", conversationId="c1")])
    g = make_token_guard("k")
    app = FastAPI()
    app.include_router(build_review_view_router(
        {"db": db, "guard": g, "require_librarian": g}))
    r = TestClient(app, raise_server_exceptions=False,
                   follow_redirects=False).get("/admin/review/c1?key=k")
    assert r.status_code != 307

def test_review_mark_updates_and_redirects_back_to_filter() -> None:
    from fastapi import FastAPI
    db = _StubDB(msgs=[_msg(id="m9", conversationId="c1")])
    guard = make_token_guard("s3cret")
    app = FastAPI()
    app.include_router(build_review_view_router(
        {"db": db, "guard": guard, "require_librarian": guard}))
    from starlette.testclient import TestClient
    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/admin/review/mark/m9?filter=refusal&key=s3cret",
              follow_redirects=False)
    assert r.status_code == 200
    assert db.updated["where"] == {"id": "m9"}
    assert db.updated["data"]["reviewedAt"] is not None
    # bounces back to the SAME filter the reviewer was working in
    assert "/admin/review?filter=refusal" in r.text
    # undo clears it
    c.get("/admin/review/mark/m9?filter=refusal&key=s3cret&undo=1")
    assert db.updated["data"] == {"reviewedAt": None, "reviewedBy": None}


def test_review_mark_401_without_token() -> None:
    from fastapi import FastAPI
    db = _StubDB(msgs=[])
    guard = make_token_guard("s3cret")
    app = FastAPI()
    app.include_router(build_review_view_router(
        {"db": db, "guard": guard, "require_librarian": guard}))
    from starlette.testclient import TestClient
    c = TestClient(app, raise_server_exceptions=False)
    assert c.get("/admin/review/mark/m9").status_code == 401


def test_tools_used_summary_prefers_the_rows_over_the_legacy_column() -> None:
    """Conversation.toolUsed is only ever written by the ARCHIVED legacy
    orchestrator, so for all v2 traffic it is empty -- and the ticket's
    one-line "Tools used:" read "none" even when the table underneath it
    listed calls."""
    db = _StubDB(
        msgs=[_msg(id="a1", type="assistant", conversationId="c1")],
        conv=SimpleNamespace(createdAt="c", updatedAt="u", toolUsed=[]),
        tools=[
            SimpleNamespace(agentName="agent", toolName="search_kb",
                            success=True, executionTime=12, timestamp="t"),
            SimpleNamespace(agentName="orchestrator", toolName="get_hours",
                            success=True, executionTime=3, timestamp="t"),
            SimpleNamespace(agentName="agent", toolName="search_kb",
                            success=True, executionTime=9, timestamp="t"),
        ],
    )
    d = _run(conversation_detail(db, "c1"))
    assert d["tools_used_summary"] == ["search_kb", "get_hours"], \
        "distinct names, first-use order"


def test_tools_used_summary_falls_back_for_pre_v2_conversations() -> None:
    """1,549 of 7,050 conversations carry the column and no rows. Those
    must keep showing what they always showed."""
    db = _StubDB(
        msgs=[_msg(id="a1", type="assistant", conversationId="c1")],
        conv=SimpleNamespace(createdAt="c", updatedAt="u",
                             toolUsed=["search_website"]),
        tools=[],
    )
    d = _run(conversation_detail(db, "c1"))
    assert d["tools_used_summary"] == ["search_website"]


def test_the_conversation_page_shows_the_whole_decision_not_just_the_text() -> None:
    from fastapi import FastAPI
    from starlette.testclient import TestClient

    db = _StubDB(
        msgs=[_msg(id="u1", type="user", content="book a room",
                   conversationId="c1"),
              _msg(id="a1", type="assistant", content="Here is how",
                   conversationId="c1", intent="room_booking",
                   scopeCampus="oxford", scopeLibrary="king",
                   confidence="high", modelUsed="gpt-5.6-luna")],
        conv=SimpleNamespace(createdAt="c", updatedAt="u", toolUsed=[]),
    )
    g = make_token_guard("k")
    app = FastAPI()
    app.include_router(build_review_view_router(
        {"db": db, "guard": g, "require_librarian": g}))
    body = TestClient(app).get("/admin/review/c1?key=k").text

    assert "room_booking" in body
    assert "oxford / king" in body
    assert "gpt-5.6-luna" in body

    # The badges belong to the ANSWER's block, not floating somewhere on
    # the page and not attached to the patron's question.
    import re

    blocks = re.findall(r"<div class='msg'>.*?</pre>", body, re.S)
    answer_block = next(b for b in blocks if "Here is how" in b)
    question_block = next(b for b in blocks if "book a room" in b)
    assert "room_booking" in answer_block
    assert "oxford / king" in answer_block
    assert "tag intent" not in question_block


def test_a_user_message_gets_no_decision_badges() -> None:
    """The patron did not classify anything; tagging their line with an
    intent would read as if they had."""
    from fastapi import FastAPI
    from starlette.testclient import TestClient

    db = _StubDB(
        msgs=[_msg(id="u1", type="user", content="hi", conversationId="c1",
                   intent="greeting", modelUsed=None, confidence=None,
                   scopeCampus=None, scopeLibrary=None)],
        conv=SimpleNamespace(createdAt="c", updatedAt="u", toolUsed=[]),
    )
    g = make_token_guard("k")
    app = FastAPI()
    app.include_router(build_review_view_router(
        {"db": db, "guard": g, "require_librarian": g}))
    body = TestClient(app).get("/admin/review/c1?key=k").text
    assert "tag intent" not in body


# --- sweeping the queue --------------------------------------------------
#
# The sweep existed for weeks and had never run: reviewedAt was null on all
# 324 flagged rows, because no page linked to it and you had to know the
# URL. Same fault the kill switch had until 2026-08-08.

def test_the_queue_offers_the_sweep():
    """It belongs where the queue is. A control you reach only by
    remembering a URL is a control nobody uses -- reviewedAt was null on
    all 324 rows, and that is why."""
    import inspect

    from src.api.admin import conversations_router as CR

    src = inspect.getsource(CR)
    # Inside the branch that runs when a flag filter is on, not somewhere
    # a reader has to go looking for.
    # index() from the sweep onwards: `body = (` appears three times in
    # this file and the first one is far above the block being checked.
    start = src.index('sweep = ""')
    branch = src[start:src.index("body = (", start)]
    assert "/admin/review/close-testing" in branch
    assert "if flag:" in branch


def test_the_hint_never_states_a_count_it_did_not_measure():
    """The counts on that page are CONVERSATIONS in a date range, not
    flagged TURNS. Using them read '761 of these came from our own
    testing' above a queue of 324."""
    import inspect

    from src.api.admin import conversations_router as CR

    src = inspect.getsource(CR)
    hint = src[src.index("NO NUMBER HERE ON PURPOSE"):]
    hint = hint[:hint.index("body = (")]
    assert "{testing_waiting}" not in hint
    assert "Most of this queue" in hint


def test_closing_needs_a_post():
    """A GET that changes 313 rows is the wrong shape whatever links to
    it -- and the old defence, that the operator had just read the count
    on the link, was hollow while nothing linked here."""
    import inspect

    from src.api.admin import review_view_router as RV

    src = inspect.getsource(RV)
    assert '@router.post("/admin/review/close-testing"' in src
    get_block = src[src.index('@router.get("/admin/review/close-testing"'):]
    get_block = get_block[:get_block.index("@router.post")]
    assert "dry_run=True" in get_block, "the GET must only preview"
    assert "dry_run=False" not in get_block


def test_the_preview_says_which_part_is_a_guess():
    """`maybe-staff` is inferred from pace and repetition, not recorded at
    the door. Closing on an inference is a judgement the operator should
    make with their eyes open."""
    import inspect

    from src.api.admin import review_view_router as RV

    src = inspect.getsource(RV)
    assert "maybe-staff" in src and "INFERRED" in src
    assert "a guess" in src


def test_a_thumbs_down_is_never_swept_whoever_pressed_it():
    """Attribution answers whether a PATRON had a bad experience. A
    thumbs-down answers whether the ANSWER was bad, and that question does
    not care who asked it -- a colleague pressing the button on a wrong
    answer is doing review work, not making noise.

    Measured 2026-08-31: the queue held 15 thumbs-downs and the sweep took
    all fifteen. Three were the same Gardner-Harvey room booking failing
    three times -- the most actionable thing in there, and the first thing
    the broom reached.
    """
    import inspect

    from src.api.admin import review_queries as RQ

    src = inspect.getsource(RQ.close_testing_rows)
    guard = src[src.index("isPositiveRated"):]
    assert "continue" in guard[:200], "a rated-down row must skip the sweep"
    # And it is reported rather than folded into "kept", or the number
    # disappears into a total nobody questions.
    assert '"rated_down"' in src


@pytest.mark.asyncio
async def test_the_sweep_holds_back_a_rated_down_testing_row():
    """The whole point, exercised rather than read off the source."""
    from src.api.admin import review_queries as RQ

    class _M:
        def __init__(self, mid, rated):
            self.id, self.conversationId = mid, "c1"
            self.isPositiveRated, self.wasRefusal = rated, True
            self.timestamp = None

    class _DB:
        class message:
            @staticmethod
            async def find_many(**kw):
                return [_M("keep", False), _M("sweep", None)]

            @staticmethod
            async def update(**kw):
                return None

    async def _sources(db, ids):
        return {"c1": {"tag": "bot", "why": "a replay"}}

    import unittest.mock as mock
    with mock.patch.object(RQ, "sources_for_conversations", _sources):
        r = await RQ.close_testing_rows(_DB(), dry_run=True)
    assert r["closed"] == 1, "the unrated testing row is swept"
    assert r["rated_down"] == 1, "the rated-down one is held and counted"
    assert r["kept"] == 1


# --- the day tally has no cliff ------------------------------------------

@pytest.mark.asyncio
async def test_the_day_tally_is_counted_in_postgres():
    """It used to read the most recent N user messages into Python. Past N
    the oldest day in the window came back short and nothing said so, and
    raising N only moves the cliff. Postgres has no N."""
    from src.api.admin import review_queries as RQ

    seen = {}

    class _DB:
        @staticmethod
        async def query_raw(sql, *params):
            seen["sql"], seen["params"] = sql, params
            return [{"day": "2026-08-30", "questions": 11},
                    {"day": "2026-08-29", "questions": 4}]

    got = await RQ.conversation_days(_DB(), limit=30)
    assert [r["questions"] for r in got] == [11, 4]
    assert not any(r["partial"] for r in got), "SQL cannot come back short"
    assert seen["params"] == ("America/New_York", 30)
    assert "GROUP BY" in seen["sql"]


@pytest.mark.asyncio
async def test_the_day_is_oxford_s_not_the_column_s():
    """The column is naive UTC. A day boundary at UTC midnight cuts
    Oxford's evening in half, and evening is when the building is
    busiest."""
    from src.api.admin import review_queries as RQ

    assert "AT TIME ZONE 'UTC' AT TIME ZONE $1" in RQ._DAYS_SQL
    # Text, not a date: handing back a date invites the driver to
    # reinterpret it in some third timezone, which is the whole class of
    # bug this lives inside.
    assert "to_char(" in RQ._DAYS_SQL


@pytest.mark.asyncio
async def test_a_stub_without_query_raw_still_gets_counts():
    """Most of the suite holds a Prisma-shaped stub. The fallback keeps
    them working -- and keeps the cliff, so it says when it hit one."""
    import datetime as _dt

    from src.api.admin import review_queries as RQ

    class _M:
        def __init__(self, ts):
            self.timestamp = ts

    when = _dt.datetime(2026, 8, 20, 18, tzinfo=_dt.timezone.utc)

    class _DB:
        class message:
            @staticmethod
            async def find_many(**kw):
                return [_M(when), _M(when)]

    got = await RQ.conversation_days(_DB(), limit=30)
    assert got == [{"day": "2026-08-20", "questions": 2, "partial": False}]


@pytest.mark.asyncio
async def test_the_fallback_marks_the_day_it_could_not_finish():
    from src.api.admin import review_queries as RQ

    import datetime as _dt

    class _M:
        def __init__(self, ts):
            self.timestamp = ts

    base = _dt.datetime(2026, 8, 20, 18, tzinfo=_dt.timezone.utc)

    class _DB:
        class message:
            @staticmethod
            async def find_many(**kw):
                take = kw.get("take") or 0
                # Exactly the cap, newest first, spanning two days.
                return ([_M(base)] * (take - 1)
                        + [_M(base - _dt.timedelta(days=1))])

    got = await RQ.conversation_days(_DB(), limit=30)
    assert got[0]["partial"] is False, "the newest day is whole"
    assert got[-1]["partial"] is True, "the oldest one is where it ran out"
