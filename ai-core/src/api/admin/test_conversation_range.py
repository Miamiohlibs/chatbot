"""Date range and "only what went wrong" on the conversations view.

WHY: /admin/conversations showed one day at a time, so the only way to see
problems across days was /admin/review (Flagged) -- which is the one thing
Flagged could do that this page could not. These two options are the
prerequisite for the two views ever becoming one.

The trap this file exists to hold: the filter has to run BEFORE the total
and before paging. Applied after, the pager advertises pages built from
rows the filter already discarded, which reads as a broken pager and sends
the operator looking for a bug that is in the page, not the data.
"""

import datetime as dt
from types import SimpleNamespace as NS

import pytest

from src.api.admin.review_queries import MAX_DAY_SPAN, list_conversations_on

_TZ = dt.timezone.utc


def _m(cid, content, type_="user", day=20, hour=15, **kw):
    return NS(id=f"{cid}-{content[:6]}-{type_}", conversationId=cid,
              content=content, type=type_,
              timestamp=dt.datetime(2026, 8, day, hour, tzinfo=_TZ),
              wasRefusal=kw.get("refusal", False),
              isPositiveRated=kw.get("rated", None),
              confidence=kw.get("confidence", "high"),
              intent=None, citedUrls=[], citedChunkIds=[], modelUsed="",
              latencyMs=0, reviewedAt=None, reviewedBy=None,
              scopeCampus=None, scopeLibrary=None)


def _pair(cid, day, *, bad=False):
    """One question and one answer, optionally a bad one."""
    return [
        _m(cid, f"question in {cid}", "user", day=day),
        _m(cid, f"answer in {cid}", "assistant", day=day,
           refusal=bad, confidence="low" if bad else "high"),
    ]


class _DB:
    def __init__(self, msgs):
        self._msgs = msgs
        self.message = NS(find_many=self._find)
        self.conversation = NS(find_many=self._convs)
        self.conversationfeedback = NS(find_many=self._none)

    async def _none(self, **_): return []
    async def _convs(self, **_): return []

    async def _find(self, where=None, order=None, take=None):
        w = where or {}
        out = list(self._msgs)
        ts = w.get("timestamp") or {}
        if ts.get("gte"):
            out = [m for m in out if m.timestamp >= ts["gte"]]
        if ts.get("lt"):
            out = [m for m in out if m.timestamp < ts["lt"]]
        if w.get("conversationId", {}).get("in") is not None:
            keep = set(w["conversationId"]["in"])
            out = [m for m in out if m.conversationId in keep]
        out.sort(key=lambda m: m.timestamp)
        return out


MSGS = (
    _pair("c-good-20", 20)
    + _pair("c-bad-20", 20, bad=True)
    + _pair("c-good-21", 21)
    + _pair("c-bad-22", 22, bad=True)
)


@pytest.mark.asyncio
async def test_one_day_is_still_one_day():
    res = await list_conversations_on(_DB(MSGS), "2026-08-20")
    assert {r["conversation_id"] for r in res["rows"]} == {
        "c-good-20", "c-bad-20"}


@pytest.mark.asyncio
async def test_a_range_reaches_every_day_in_it():
    res = await list_conversations_on(_DB(MSGS), "2026-08-20",
                                      day_to="2026-08-22")
    assert res["total"] == 4


@pytest.mark.asyncio
async def test_the_end_of_the_range_is_inclusive():
    """An operator picking the 20th to the 22nd means three days. Reading
    the end as exclusive silently drops the day they were looking for."""
    res = await list_conversations_on(_DB(MSGS), "2026-08-22",
                                      day_to="2026-08-22")
    assert {r["conversation_id"] for r in res["rows"]} == {"c-bad-22"}


@pytest.mark.asyncio
async def test_needs_only_keeps_the_ones_something_went_wrong_in():
    res = await list_conversations_on(_DB(MSGS), "2026-08-20",
                                      day_to="2026-08-22", needs_only=True)
    assert {r["conversation_id"] for r in res["rows"]} == {
        "c-bad-20", "c-bad-22"}


@pytest.mark.asyncio
async def test_the_total_counts_what_survived_the_filter():
    """The trap. Filtering after the count gives a pager built from rows
    the filter already threw away."""
    res = await list_conversations_on(_DB(MSGS), "2026-08-20",
                                      day_to="2026-08-22", needs_only=True)
    assert res["total"] == 2, res["total"]


@pytest.mark.asyncio
async def test_paging_a_filtered_range_does_not_leak_filtered_rows():
    res = await list_conversations_on(_DB(MSGS), "2026-08-20",
                                      day_to="2026-08-22", needs_only=True,
                                      limit=1, offset=0)
    assert len(res["rows"]) == 1
    assert res["rows"][0]["conversation_id"].startswith("c-bad")
    second = await list_conversations_on(_DB(MSGS), "2026-08-20",
                                         day_to="2026-08-22",
                                         needs_only=True, limit=1, offset=1)
    assert second["rows"][0]["conversation_id"].startswith("c-bad")
    assert (second["rows"][0]["conversation_id"]
            != res["rows"][0]["conversation_id"])


@pytest.mark.asyncio
async def test_an_over_wide_range_is_clamped_and_says_so():
    res = await list_conversations_on(_DB(MSGS), "2026-08-20",
                                      day_to="2027-08-20")
    assert res["clamped"] is True


@pytest.mark.asyncio
async def test_an_ordinary_range_is_not_marked_clamped():
    res = await list_conversations_on(_DB(MSGS), "2026-08-20",
                                      day_to="2026-08-22")
    assert res["clamped"] is False


@pytest.mark.asyncio
async def test_a_backwards_range_falls_back_to_one_day():
    """Two date pickers can be filled in either order. An end before the
    start must not produce an empty page that looks like no traffic."""
    res = await list_conversations_on(_DB(MSGS), "2026-08-22",
                                      day_to="2026-08-20")
    assert {r["conversation_id"] for r in res["rows"]} == {"c-bad-22"}


@pytest.mark.asyncio
async def test_the_span_cap_is_the_documented_one():
    assert MAX_DAY_SPAN == 31
