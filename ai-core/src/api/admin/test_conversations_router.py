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
    def __init__(self, msgs, dev_convs=(), origins=None):
        self._origins = origins or {}
        self.message = NS(find_many=self._find)
        # The dev flag lives here, not on Message: a turn that reached the
        # server with no browser origin is tagged v2_turn_dev.
        self.modeltokenusage = NS(find_many=self._usage)
        # origin lives on Conversation, and is the strongest signal there
        # is -- somebody came through the staff link on purpose.
        self.conversation = NS(find_many=self._convs)
        self._msgs = msgs
        self._dev = set(dev_convs)
        self.seen_where = None

    async def _usage(self, where=None, **_):
        return [NS(conversationId=c, callSite="v2_turn_dev") for c in self._dev]

    async def _convs(self, where=None, **_):
        return [NS(id=c, origin=o) for c, o in getattr(self, "_origins", {}).items()]

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
    assert len((await list_conversations_on(db, "2026-08-21"))["rows"]) == 1
    assert (await list_conversations_on(db, "2026-08-22"))["rows"] == []


@pytest.mark.asyncio
async def test_sessions_where_nobody_typed_are_left_out():
    # The widget opens a socket on page load, so most conversation rows have
    # no question in them at all. Listing those buries the ones that do.
    noon = dt.datetime(2026, 8, 21, 12, tzinfo=NY)
    db = _DB([_msg("empty", noon, "assistant", "greeting"),
              _msg("real", noon, "user", "when do you close")])
    rows = (await list_conversations_on(db, "2026-08-21"))["rows"]
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
    r = (await list_conversations_on(db, "2026-08-21"))["rows"][0]
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
    assert (await list_conversations_on(db, "2026-08-21"))["rows"][0]["needs_look"] is False


@pytest.mark.asyncio
async def test_newest_conversation_first():
    d = lambda h: dt.datetime(2026, 8, 21, h, tzinfo=NY)  # noqa: E731
    db = _DB([_msg("morning", d(9)), _msg("evening", d(19)), _msg("noon", d(12))])
    rows = (await list_conversations_on(db, "2026-08-21"))["rows"]
    assert [r["conversation_id"] for r in rows] == ["evening", "noon", "morning"]


@pytest.mark.asyncio
async def test_a_malformed_day_returns_nothing_instead_of_raising():
    assert (await list_conversations_on(_DB([]), "yesterday"))["rows"] == []
    assert (await list_conversations_on(_DB([]), ""))["rows"] == []


@pytest.mark.asyncio
async def test_a_database_failure_empties_the_page_rather_than_500ing():
    class _Boom:
        def __init__(self):
            self.message = NS(find_many=self._raise)
            self.modeltokenusage = NS(find_many=self._raise)
            self.conversation = NS(find_many=self._raise)

        async def _raise(self, **_):
            raise RuntimeError("postgres is having a moment")

    assert (await list_conversations_on(_Boom(), "2026-08-21"))["rows"] == []


# --- pagination ------------------------------------------------------------


def _many(n: int, hour: int = 12):
    """n conversations, one question each, one minute apart."""
    base = dt.datetime(2026, 8, 21, hour, tzinfo=NY)
    return [_msg(f"c{i}", base + dt.timedelta(minutes=i), "user", f"q{i}")
            for i in range(n)]


@pytest.mark.asyncio
async def test_the_total_is_the_whole_day_not_the_page():
    # A page that shows 50 without saying there are 120 hides 70 of them.
    res = await list_conversations_on(_DB(_many(120)), "2026-08-21", limit=50)
    assert res["total"] == 120
    assert len(res["rows"]) == 50


@pytest.mark.asyncio
async def test_paging_walks_the_whole_day_without_repeats_or_gaps():
    db = _DB(_many(120))
    seen = []
    for page in range(3):
        res = await list_conversations_on(db, "2026-08-21", limit=50,
                                          offset=page * 50)
        seen += [r["conversation_id"] for r in res["rows"]]
    assert len(seen) == 120
    assert len(set(seen)) == 120, "a conversation appeared on two pages"


@pytest.mark.asyncio
async def test_an_offset_past_the_end_returns_nothing_rather_than_raising():
    res = await list_conversations_on(_DB(_many(5)), "2026-08-21",
                                      limit=50, offset=500)
    assert res["rows"] == [] and res["total"] == 5


# --- source labels ---------------------------------------------------------


@pytest.mark.asyncio
async def test_a_scripted_conversation_is_labelled_local_test():
    noon = dt.datetime(2026, 8, 21, 12, tzinfo=NY)
    db = _DB([_msg("scripted", noon, "user", "hi")], dev_convs=["scripted"])
    r = (await list_conversations_on(db, "2026-08-21"))["rows"][0]
    assert r["source"]["label"] == "local test"
    assert r["source"]["why"], "a label with no reason is a label nobody trusts"


@pytest.mark.asyncio
async def test_a_browser_conversation_gets_no_label():
    # "patron" is never asserted -- the system stores no identity, so the
    # honest answer to "who was this" is silence.
    noon = dt.datetime(2026, 8, 21, 12, tzinfo=NY)
    db = _DB([_msg("real", noon, "user", "when do you close")])
    r = (await list_conversations_on(db, "2026-08-21"))["rows"][0]
    assert r["source"]["label"] == ""


@pytest.mark.asyncio
async def test_a_fast_run_of_unrelated_questions_is_flagged_as_maybe_staff():
    base = dt.datetime(2026, 8, 21, 12, tzinfo=NY)
    db = _DB([_msg("batch", base + dt.timedelta(seconds=20 * i), "user", f"q{i}")
              for i in range(8)])
    r = (await list_conversations_on(db, "2026-08-21"))["rows"][0]
    assert r["source"]["label"] == "staff?"
    assert "median" in r["source"]["why"]


@pytest.mark.asyncio
async def test_relaying_somebody_elses_question_is_flagged_as_maybe_staff():
    noon = dt.datetime(2026, 8, 21, 12, tzinfo=NY)
    db = _DB([_msg("relay", noon, "user",
                   "I have a student who needs the AP style manual")])
    r = (await list_conversations_on(db, "2026-08-21"))["rows"][0]
    assert r["source"]["label"] == "staff?"


@pytest.mark.asyncio
async def test_a_patient_multi_question_session_is_not_called_staff():
    # Six questions over an hour is somebody working, not somebody testing.
    base = dt.datetime(2026, 8, 21, 12, tzinfo=NY)
    db = _DB([_msg("slow", base + dt.timedelta(minutes=10 * i), "user", f"q{i}")
              for i in range(6)])
    r = (await list_conversations_on(db, "2026-08-21"))["rows"][0]
    assert r["source"]["label"] == ""


# --- the staff-test link ---------------------------------------------------


@pytest.mark.asyncio
async def test_arriving_through_the_staff_link_is_recorded_not_guessed():
    noon = dt.datetime(2026, 8, 21, 12, tzinfo=NY)
    db = _DB([_msg("c1", noon, "user", "when do you close")],
             origins={"c1": "staff"})
    r = (await list_conversations_on(db, "2026-08-21"))["rows"][0]
    assert r["source"]["label"] == "staff test"
    assert r["source"]["tag"] == "staff"
    assert "not inferred" in r["source"]["why"]


@pytest.mark.asyncio
async def test_the_staff_link_outranks_every_transcript_guess():
    # A recorded fact beats any amount of clever reading. If somebody came
    # through the staff link AND types like a patron, they are still staff.
    noon = dt.datetime(2026, 8, 21, 12, tzinfo=NY)
    db = _DB([_msg("c1", noon, "user", "hi")], origins={"c1": "staff"})
    assert (await list_conversations_on(db, "2026-08-21"))["rows"][0]["source"]["tag"] == "staff"


# --- filtering by source ---------------------------------------------------


def _mixed():
    base = dt.datetime(2026, 8, 21, 12, tzinfo=NY)
    msgs = ([_msg("staff1", base, "user", "hello")]
            + [_msg("script1", base, "user", "hello")]
            + [_msg("plain1", base, "user", "when do you close")]
            + [_msg("plain2", base, "user", "do you loan software")])
    return _DB(msgs, dev_convs=["script1"], origins={"staff1": "staff"})


@pytest.mark.asyncio
async def test_each_source_filter_returns_only_that_group():
    db = _mixed()
    for src, expect in (("staff", {"staff1"}), ("local", {"script1"}),
                        ("patron", {"plain1", "plain2"})):
        rows = (await list_conversations_on(db, "2026-08-21", source=src))["rows"]
        assert {r["conversation_id"] for r in rows} == expect, src


@pytest.mark.asyncio
async def test_no_filter_returns_everything():
    rows = (await list_conversations_on(_mixed(), "2026-08-21"))["rows"]
    assert len(rows) == 4


@pytest.mark.asyncio
async def test_the_badge_counts_the_whole_day_not_the_page():
    # A count that shrinks when you turn the page is worse than no count.
    db = _mixed()
    res = await list_conversations_on(db, "2026-08-21", limit=1)
    assert len(res["rows"]) == 1
    assert res["source_counts"][""] == 4
    assert res["source_counts"]["staff"] == 1
    assert res["source_counts"]["patron"] == 2


@pytest.mark.asyncio
async def test_a_filtered_total_is_the_filtered_count_not_the_day_count():
    # Otherwise the pager offers pages the filter cannot fill.
    res = await list_conversations_on(_mixed(), "2026-08-21", source="staff")
    assert res["total"] == 1
