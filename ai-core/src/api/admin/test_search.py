"""Keyword search across conversations.

WHY: the console had none. Conversations browse one day at a time, Flagged
filters by preset, tickets by status -- so "has anyone ever asked about
Zotero" meant opening days one after another and reading them. Every
question about what patrons actually ask was gated behind that.
"""

import datetime as dt
from types import SimpleNamespace as NS

import pytest

from src.api.admin.review_queries import SEARCH_SCAN_CAP, search_messages


def _m(cid, content, type_="user", day=20):
    return NS(id=f"{cid}-{content[:6]}", conversationId=cid, content=content,
              type=type_,
              timestamp=dt.datetime(2026, 8, day, 15, tzinfo=dt.timezone.utc))


class _DB:
    def __init__(self, msgs, blow_up=False):
        self._msgs = msgs
        self._blow_up = blow_up
        self.message = NS(find_many=self._find)

    async def _find(self, where=None, order=None, take=None):
        if self._blow_up:
            raise RuntimeError("database is on fire")
        w = where or {}
        out = list(self._msgs)
        c = (w.get("content") or {}).get("contains")
        if c:
            out = [m for m in out if c.lower() in (m.content or "").lower()]
        if w.get("type"):
            out = [m for m in out if m.type == w["type"]]
        out.sort(key=lambda m: m.timestamp, reverse=True)
        return out[:take] if take else out


MSGS = [
    _m("c-1", "do you have Zotero help", day=20),
    _m("c-1", "Yes -- the Citation Managers guide covers Zotero.",
       "assistant", day=20),
    _m("c-2", "how do I cite in APA", day=21),
    _m("c-3", "is zotero free", day=22),
    _m("c-3", "Zotero is free.", "assistant", day=22),
]


@pytest.mark.asyncio
async def test_it_finds_the_word_across_days():
    res = await search_messages(_DB(MSGS), "zotero")
    assert {r["conversation_id"] for r in res["rows"]} == {"c-1", "c-3"}
    assert res["total"] == 2


@pytest.mark.asyncio
async def test_matching_is_case_insensitive():
    assert (await search_messages(_DB(MSGS), "ZOTERO"))["total"] == 2


@pytest.mark.asyncio
async def test_one_row_per_conversation_not_per_message():
    """Ten hits in one chat is one thing to read, not ten."""
    res = await search_messages(_DB(MSGS), "zotero")
    c1 = next(r for r in res["rows"] if r["conversation_id"] == "c-1")
    assert c1["hits"] == 2
    assert len(res["rows"]) == 2


@pytest.mark.asyncio
async def test_newest_conversation_first():
    res = await search_messages(_DB(MSGS), "zotero")
    assert res["rows"][0]["conversation_id"] == "c-3"


@pytest.mark.asyncio
async def test_who_narrows_to_the_patron_or_the_bot():
    """Two different questions -- "did anyone ask about X" and "did we ever
    tell someone X" -- need different halves of the transcript."""
    patron = await search_messages(_DB(MSGS), "zotero", who="patron")
    assert all(r["snippet_from"] == "patron" for r in patron["rows"])
    bot = await search_messages(_DB(MSGS), "zotero", who="bot")
    assert all(r["snippet_from"] == "chatbot" for r in bot["rows"])
    assert bot["total"] == 2


@pytest.mark.asyncio
async def test_a_one_character_query_is_refused_rather_than_matching_everything():
    res = await search_messages(_DB(MSGS), "z")
    assert res["rows"] == [] and res["total"] == 0


@pytest.mark.asyncio
async def test_blank_and_whitespace_queries_return_nothing():
    for q in ("", "   ", None):
        assert (await search_messages(_DB(MSGS), q))["total"] == 0


@pytest.mark.asyncio
async def test_hitting_the_scan_cap_is_declared_not_hidden():
    """A confident partial answer is worse than a truncated one that says
    so. The cap exists so growth stops the search loudly."""
    many = [_m(f"c-{i}", "zotero", day=20) for i in range(SEARCH_SCAN_CAP)]
    res = await search_messages(_DB(many), "zotero")
    assert res["truncated"] is True


@pytest.mark.asyncio
async def test_an_ordinary_result_is_not_marked_truncated():
    assert (await search_messages(_DB(MSGS), "zotero"))["truncated"] is False


@pytest.mark.asyncio
async def test_a_database_failure_does_not_500_the_console():
    res = await search_messages(_DB(MSGS, blow_up=True), "zotero")
    assert res["error"] is True
    assert res["rows"] == []


@pytest.mark.asyncio
async def test_a_message_with_no_conversation_is_skipped():
    orphan = NS(id="x", conversationId=None, content="zotero", type="user",
                timestamp=dt.datetime(2026, 8, 20, tzinfo=dt.timezone.utc))
    res = await search_messages(_DB([orphan] + MSGS), "zotero")
    assert all(r["conversation_id"] for r in res["rows"])
    assert res["total"] == 2
