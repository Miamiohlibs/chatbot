"""Tests for the by-day conversations view."""

import datetime as dt
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

import pytest

from src.api.admin.conversations_router import shift_day, today_local
from src.api.admin.review_queries import list_conversations_on

NY = ZoneInfo("America/New_York")


def _msg(cid, ts, type_="user", content="q", **kw):
    return NS(conversationId=cid, timestamp=ts, type=type_, content=content,
              wasRefusal=kw.get("refusal", False),
              isPositiveRated=kw.get("rated", None),
              confidence=kw.get("confidence", "high"))


class _DB:
    def __init__(self, msgs):
        self.message = NS(find_many=self._find)
        self._msgs = msgs
        self.seen_where = None

    async def _find(self, where=None, order=None, take=None):
        self.seen_where = where
        rng = (where or {}).get("timestamp") or {}
        out = self._msgs
        if "gte" in rng:
            out = [m for m in out if m.timestamp >= rng["gte"]]
        if "lt" in rng:
            out = [m for m in out if m.timestamp < rng["lt"]]
        if (where or {}).get("type"):
            out = [m for m in out if m.type == where["type"]]
        return out


def test_day_navigation_is_calendar_arithmetic():
    assert shift_day("2026-08-21", -1) == "2026-08-20"
    assert shift_day("2026-08-01", -1) == "2026-07-31"   # across a month
    assert shift_day("2026-03-01", -1) == "2026-02-28"   # non-leap February


def test_a_broken_date_falls_back_to_today_rather_than_500ing():
    assert shift_day("not-a-date", -1) == today_local()


@pytest.mark.asyncio
async def test_an_evening_conversation_lands_on_the_oxford_day_not_the_utc_one():
    """20:00 in Oxford is 00:00 UTC the NEXT day.

    Bucketing on UTC put every evening's traffic on tomorrow's page -- and
    evening is when the building is busiest. The cost dashboard had this
    exact bug; this asserts the fix rather than trusting it.
    """
    evening = dt.datetime(2026, 8, 21, 20, 30, tzinfo=NY)
    assert evening.astimezone(dt.timezone.utc).date().isoformat() == "2026-08-22"

    db = _DB([_msg("c1", evening), _msg("c1", evening, "assistant", "a")])
    assert len(await list_conversations_on(db, "2026-08-21")) == 1
    assert await list_conversations_on(db, "2026-08-22") == []


@pytest.mark.asyncio
async def test_sessions_where_nobody_typed_are_left_out():
    # The widget opens a socket on page load, so most conversation rows have
    # no question in them at all. Listing those buries the ones that do.
    noon = dt.datetime(2026, 8, 21, 12, tzinfo=NY)
    db = _DB([_msg("empty", noon, "assistant", "greeting"),
              _msg("real", noon, "user", "when do you close")])
    rows = await list_conversations_on(db, "2026-08-21")
    assert [r["conversation_id"] for r in rows] == ["real"]


@pytest.mark.asyncio
async def test_a_row_carries_the_signals_that_make_it_worth_opening():
    noon = dt.datetime(2026, 8, 21, 12, tzinfo=NY)
    db = _DB([
        _msg("c", noon, "user", "first"),
        _msg("c", noon, "assistant", "a", refusal=True),
        _msg("c", noon, "user", "second"),
        _msg("c", noon, "assistant", "b", rated=False, confidence="low"),
    ])
    r = (await list_conversations_on(db, "2026-08-21"))[0]
    assert r["asked"] == 2
    assert r["first_question"] == "first"
    assert r["refusals"] == 1 and r["thumbs_down"] == 1
    assert r["low_confidence"] == 1
    assert r["needs_look"] is True


@pytest.mark.asyncio
async def test_a_clean_conversation_is_not_flagged_for_a_look():
    noon = dt.datetime(2026, 8, 21, 12, tzinfo=NY)
    db = _DB([_msg("c", noon, "user", "hi"),
              _msg("c", noon, "assistant", "hello")])
    assert (await list_conversations_on(db, "2026-08-21"))[0]["needs_look"] is False


@pytest.mark.asyncio
async def test_newest_conversation_first():
    d = lambda h: dt.datetime(2026, 8, 21, h, tzinfo=NY)  # noqa: E731
    db = _DB([_msg("morning", d(9)), _msg("evening", d(19)), _msg("noon", d(12))])
    rows = await list_conversations_on(db, "2026-08-21")
    assert [r["conversation_id"] for r in rows] == ["evening", "noon", "morning"]


@pytest.mark.asyncio
async def test_a_malformed_day_returns_nothing_instead_of_raising():
    assert await list_conversations_on(_DB([]), "yesterday") == []
    assert await list_conversations_on(_DB([]), "") == []


@pytest.mark.asyncio
async def test_a_database_failure_empties_the_page_rather_than_500ing():
    class _Boom:
        def __init__(self):
            self.message = NS(find_many=self._raise)

        async def _raise(self, **_):
            raise RuntimeError("postgres is having a moment")

    assert await list_conversations_on(_Boom(), "2026-08-21") == []
